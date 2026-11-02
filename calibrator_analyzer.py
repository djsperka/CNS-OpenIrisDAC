import numpy as np 
from scipy.optimize import curve_fit as curve_fit
from open_iris_client import EyesData, Point
from shared_resources import in_cal_lock
from dac_common import CalibrationParameters
from dataclasses import dataclass
from typing import List
from collections import defaultdict as defaultdict
import time
from threading import Thread
from queue import Queue, Empty
from globalstate import GlobalState
import logging
from enum import Enum
import datetime
import pickle
from numpy_ringbuffer import RingBuffer

logger = logging.getLogger("Calibrator")

binding_id = None


class TWrapperClass:

    def __init__(self, x_bias, y_bias):
        self.cal = CalibrationParameters(x_bias=x_bias, y_bias=y_bias,x_gain=1,y_gain=1,rotation=0)
    
    def get_cal(self, x_gain, y_gain, degrees):
        self.cal.x_gain = x_gain
        self.cal.y_gain = y_gain
        self.cal.rotation = degrees
        return self.cal

    def do_transform(self, xy, x_gain, y_gain, degrees):
        self.cal.x_gain = x_gain
        self.cal.y_gain = y_gain
        self.cal.rotation = degrees
        pp = self.cal.transform(Point(xy[0], xy[1]))
        return np.array([pp.x, pp.y])

    def func(self, xydata, x_gain, y_gain, degrees):
        """Wrapper function for curve_fit. xydata expected to be Mx2. We apply the transform specified
        by x_gain, y_gain and degrees along the "0" axis. The results of each are also stacked, and the
        array returned by apply_along_axis is ZZZZZZ. We ravel() that -- curve_fit wants a 1-D result. 

        Args:
            xydata (_type_): _description_
            x_gain (_type_): _description_
            y_gain (_type_): _description_
            degrees (_type_): _description_

        Returns:
            _type_: _description_
        """
        #logger.info(f"wrapper.func: xydata shape is {np.shape(xydata)}")
        pdata = np.apply_along_axis(self.do_transform, 0, xydata, x_gain, y_gain, degrees)
        return pdata.ravel()



@dataclass
class ButtonPressInfo:
    ind: int
    vx: float
    vy: float
    frameind: int
    checked: bool


@dataclass
class CalibrationMeasurement:
    """Mean values over the analysis window around a good button press. Each is shape (2,)."""
    fixpt: np.ndarray
    pupil: np.ndarray
    cr: np.ndarray
    p4: np.ndarray

    @property
    def crsig(self):
        return self.cr - self.pupil

    @property
    def dpisig(self):
        return self.cr - self.p4


# One record per frame in the calibration ring buffer. 'frame' is the absolute frame counter,
# 'button' is True only on the frame where a button press was accepted, 'fixpt' is the
# fixation point position active on that frame.
FRAME_DTYPE = np.dtype([('frame', np.int64), ('pupil', float, 2), ('cr', float, 2),
                        ('p4', float, 2), ('button', bool), ('fixpt', float, 2)])



class Calibrator(Thread):

    class States(Enum):
        INITIALIZE=1
        LOAD=3
        CHECK=4
        IDLE=5
        DONE=99

    def __init__(self, gs:GlobalState):
        super().__init__()
        self.globalstate = gs
        self._stopnow = False

        # initialize first, skip state INITIALIZE
        self.initialize_calibration()
        self._state = self.States.IDLE
        logger.info("calibrator is ready")

    def initialize_calibration(self):
        self._fps = self.globalstate.capture_fps
        self._nbefore = int(np.floor(self.globalstate.calibration_before_sec * self._fps))
        self._nafter = int(np.floor(self.globalstate.calibration_after_sec * self._fps))
        self._vmax = self.globalstate.calibration_vmax_px_per_sec/self._fps

        # Ring buffer for frame data. A button press is analyzed on the first frame where
        # ind+nafter < counter, so nbefore+nafter+1 frames are needed. Double it for slack.
        self._rb_capacity = 2 * (self._nbefore + self._nafter + 1)
        self._rb = RingBuffer(self._rb_capacity, dtype=FRAME_DTYPE)
        logger.info(f"Created ring buffer with capacity {self._rb_capacity} frames.")

        # good measurements saved here
        self._meas = defaultdict(list)
        self._cal = CalibrationParameters(0,0,1,1,0)
        self._have_cal = False
        
        # these are for state management
        self._counter = 0
        self._button_up = True
        self._button_list: List[ButtonPressInfo] = [] # (index,x,y)
        self._framesig_on = False
        self._framesig_on_at = 0

        # when using analyze_loop() as target of a Thread. Append EyeData to this. 
        self._queue = Queue()

    def stop(self):
        self._stopnow = True

    def get_cal(self):
        return self._have_cal, self._cal

    def clear_cal(self):

        # clear calibration and data
        self._have_cal = False

        # empty the ring buffer
        self._rb = RingBuffer(self._rb_capacity, dtype=FRAME_DTYPE)
        logger.info(f"Cleared ring buffer with capacity {self._rb_capacity} frames.")

        # reset measurements
        self._meas = defaultdict(list)
        self._cal = CalibrationParameters(0,0,1,1,0)
        self._have_cal = False
        
        # reset state
        self._counter = 0
        self._button_up = True
        self._button_list: List[ButtonPressInfo] = [] # (index,x,y)
        self._framesig_on = False
        self._framesig_on_at = 0

    def run(self):

        idle_wait = 0.1    # sleep time in idle loop
        data_timeout = 1/self.globalstate.capture_fps
        logger.info(f"Capture fps {self.globalstate.capture_fps}, data_timeout {data_timeout}")

        # loop over this cycle until we're told to stop
        while self._state != self.States.DONE:

            if self._state == self.States.INITIALIZE:
                logger.info("entering INITIALIZE")
                self.initialize_calibration()
                self._state = self.States.IDLE
            elif self._state == self.States.IDLE:
                # wait for globalstate to say we're calibrating. 
                # we could get stopped while waiting, though, so take care of that.
                if self._stopnow:
                    self._state = self.States.DONE
                elif self.globalstate.calibrating:
                   logger.info("entering CHECK")
                   self._state = self.States.CHECK
                elif self.globalstate.loading:
                    self._state = self.States.LOAD
                else:
                    time.sleep(idle_wait)
            elif self._state == self.States.CHECK:
                # check for stop, and check for pause
                if self._stopnow:
                    self._state = self.States.DONE
                elif not self.globalstate.calibrating:
                    logger.info("CHECK done - enter IDLE")
                    self._state = self.States.IDLE
                else:
                    try:
                        # fetch from the queue with a timeout. The timeout should be approx 1/capture rate. 
                        ed=self.globalstate.calibration_queue.get(block=True, timeout=data_timeout)
                        self.step(ed)
                        with in_cal_lock:
                            self.globalstate.calibration_frames_out += 1
                    except Empty:
                        continue

    def load_measurements(self, pathToUse):
        meas = defaultdict(list)
        counter = 0
        try:
            with open(pathToUse, 'r') as f:
                for line in f:
                    s=[float(v) for v in line.split(',')]
                    fixpt = np.array([s[0], s[1]])
                    if len(s) >= 8:
                        m = CalibrationMeasurement(fixpt, np.array(s[2:4]), np.array(s[4:6]), np.array(s[6:8]))
                    else:
                        # legacy format: fx,fy,crsig_x,crsig_y. Keep crsig (cr-pupil) intact.
                        m = CalibrationMeasurement(fixpt, np.zeros(2), np.array(s[2:4]), np.full(2, np.nan))
                    meas[(s[0], s[1])].append(m)
                    counter = counter+1
        except Exception as e:
            print(e)
            print('Error loading calibration measurements file.')
        logger.info(f"Loaded {counter} lines from {pathToUse}")
        self._meas = meas
        return counter

    def save_measurements(self, pathToUse, meas):
        with open(pathToUse, 'w') as f:
            for (key,pts) in meas.items():
                for p in pts:
                    f.write(f"{key[0]:f},{key[1]:f},{p.pupil[0]:f},{p.pupil[1]:f},{p.cr[0]:f},{p.cr[1]:f},{p.p4[0]:f},{p.p4[1]:f}\n")

    @property
    def measurements(self):
        return self._meas

    @measurements.setter
    def measurements(self, m:defaultdict):
        self._meas = m

    @property
    def counter(self):
        return self._counter

    def step(self, ed: EyesData):
        data_ok = True

        # I'm not sure what constitutes bad pupil data.
        # assume that x should be in [0,720] and y in [0,450]
        # CR data is bad if x or y is set to -100.
        # P4 data is bad if the x value is the max (720) plus 100 (=820), or the y value is -100.
        if ed.left.pupil.x < 0 or ed.left.pupil.x > 720 or ed.left.pupil.y < 0 or ed.left.pupil.y > 450:
            pupil = (np.nan, np.nan)
            data_ok = False
        else:
            pupil = (ed.left.pupil.x, ed.left.pupil.y)

        if ed.left.cr.x == -100 or ed.left.cr.y == -100:
            cr = (np.nan, np.nan)
            data_ok = False
        else:
            cr = (ed.left.cr.x, ed.left.cr.y)

        if ed.left.p4.x == 820 or ed.left.p4.y == -100:
            p4 = (np.nan, np.nan)
            data_ok = False
        else:
            p4 = (ed.left.p4.x, ed.left.p4.y)

        fixpt = (ed.extra.doubles[7], ed.extra.doubles[8])
        button_accepted = False

        button_is_pressed = ed.extra.ints[8] & 0x1
        framesig_present = ed.extra.ints[0] & 0x1

        # djs - The frame signals are not reliably received by the camera. The frame signal can be rather short - 
        # half the VSG frame time, so it can be approx 4-5ms. If the camera is sampling at 500FPS, then this is OK. 
        # If the camera is sampling at 100Hz, then the frame signals can be missed entirely.
        # This means that we (for now) will take the messages received by the CalibratorComm as true: when assume that 
        # when a msg is received (e.g. F 0,0,1,red), then the fixpt is at that point. 
        # The code here that checks for the frame signal is ignored. 

        if not self._framesig_on:
            if framesig_present:
                self._framesig_on_at = self._counter
                self._framesig_on = True
        else:
            # framesig_on is True, meaning the last time through the FRAME signal was present.
            # We only need to check if framesig is not present this time.
            if not framesig_present:
                self._framesig_on = False

        # button_is_pressed is set according to the dio bits read in the dio thread, and which are assigned to 
        # extra.Ints[0]. The _button_up var maintains the button state across frames. Below we look for the 
        # frame where the button press is first detected. If that is the case, save the button press in the 
        # button list. 
        #
        # Originally, the button info was saved ONLY IF the current data was OK - i.e. pupil, CR, and P4 data were
        # all good. This is probably too restrictive, saving the button info regardless. The button check will filter
        # out bad data.
        # 
        # Updated to check value of calibration_fixation_on, which approximates the time when the fixpt is on screen. 
        # If button is pressed when a fixpt is NOT on, we will ignore it.
        # Only one button press is accepted per fixpt (calibration_fixation_button_accepted is reset
        # when a new fixpt is presented).

        if self._button_up:
            if button_is_pressed:
                self._button_up = False
                with in_cal_lock:
                    if self.globalstate.calibration_fixation_on:
                        if not self.globalstate.calibration_fixation_button_accepted:
                            self._button_list.append(ButtonPressInfo(self.counter, fixpt[0], fixpt[1], self._framesig_on_at, False))
                            self.globalstate.calibration_fixation_button_accepted = True    # only one button per fixpt
                            button_accepted = True
                            logger.info(f"Button at {self.counter} x={fixpt[0]}, y={fixpt[1]}")
                        else:
                            logger.info("Button already pressed for this fixation point. Ignoring.")
                    else:
                        logger.info(f"Button pressed when no fixpt on screen. Ignoring button press.")

        else:
            if not button_is_pressed:
                self._button_up = True

        self._rb.append((self._counter, pupil, cr, p4, button_accepted, fixpt))
        self._counter += 1
        self._button_ana()
        return self._counter

    def _get_window(self, start:int, stop:int):
        """Get frames [start, stop) (absolute frame numbers) from the ring buffer, oldest first.

        Returns:
            structured ndarray (FRAME_DTYPE) of length stop-start, or None if the frames are not
            all in the buffer.
        """
        # absolute frame number of the oldest frame in the buffer (logical index 0)
        oldest = self._counter - len(self._rb)
        if start < oldest or stop > self._counter or stop <= start:
            logger.warning(f"Frames [{start},{stop}) not in ring buffer (holds [{oldest},{self._counter}))")
            return None
        # RingBuffer maps non-negative logical indices to the underlying storage, so these come out in order
        w = self._rb[np.arange(start - oldest, stop - oldest)]
        if w['frame'][0] != start or not np.all(np.diff(w['frame']) == 1):
            logger.warning(f"Frames extracted from ring buffer are out of order for [{start},{stop})")
            return None
        return w

    def get_crsig(self, w):
        """Get CR signal (cr-pupil) for a window from _get_window().

        Returns:
            ndarray: row 0/1 is x/y value. shape=(2,M)
        """
        return (w['cr'] - w['pupil']).T

    def get_dpisig(self, w):
        return (w['cr'] - w['p4']).T

    def _check_velocity(self, xy, vmax):
        """Check that velocity (in x and y separately) is less than vmax in the range defined by ind, nbefore, and nafter.

        Args:
            xy (numpy array nframes x 2): xy values
            ind (int): index of button press
            nbefore (int): nframes before button press to include in tests
            nafter (int): nframes after button press blah blah
            vmax (float): max velocity 
        """
        v = np.diff(xy, axis=1)
        return np.all(np.abs(v[:,:]) < vmax)


    def _button_ana(self):
        """Using the current button_list, perform checks on each entry that has not been checked."""
        for binf in self._button_list:
            if not binf.checked:
                if binf.vx < 900 and binf.vy < 900:
                    if binf.ind+self._nafter < self._counter:
                        w = self._get_window(binf.ind-self._nbefore, binf.ind+self._nafter)
                        if w is not None and self._check_velocity(self.get_crsig(w), self._vmax):
                            m = CalibrationMeasurement(np.array([binf.vx, binf.vy]),
                                                       w['pupil'].mean(axis=0), w['cr'].mean(axis=0), w['p4'].mean(axis=0))
                            self._meas[(binf.vx,binf.vy)].append(m)
                        binf.checked = True
                else:
                    binf.checked = True # weird initialization values here

    def dofit(self):
        # The items in the measurements dict are lists. Each list element
        # is a CalibrationMeasurement - its crsig is the (x,y) of that crsig measurement.
        # The stim position is in the key, which is a tuple (stimx_degrees, stimy_degrees)
        # This method attempts to fit the measurements to the stim positions. On success,
        # self._cal is set, and self._have_cal==True.

        target_xy_list=[]
        measured_xy_list = []
        bias = (0,0)
        for i, (key,pts) in enumerate(self._meas.items()):
            if key == (0,0):
                # get the mean of these - this is the bias
                bias = np.stack([p.crsig for p in pts]).mean(axis=0)
                logger.info(f"Used {len(pts)} to get bias: {bias}")
            else:
                for p in pts:
                    target_xy_list.append(key)
                    measured_xy_list.append(p.crsig)

        # Multiply the target xy by the volts per degree in x and y. Then pass the target _volts_ as a 1D array 
        # so all x values are first, then the y values. Results from the wrapper func should be ravel()d like this. 
        # pass measured values the same, but don't ravel(). That is, row 0 is x, row 1 is y. This gets passed to the 
        # func without any modification. 

        logger.info(f"Fit will use {len(target_xy_list)} measurements")
        target_xy_for_fit = (np.stack(target_xy_list)*(self.globalstate.calibration_vpdx,self.globalstate.calibration_vpdy)).T.ravel()
        measured_xy_for_fit = np.stack(measured_xy_list).T

        # initial values for parameters. 
        # TODO - these should be the current calibration parameters? 

        # initial guess for x_gain, y_gain, degrees
        p0 = np.array([.2,.2,0])

        # limits for same
        low_limits = np.array([0.1, 0.1, -10])
        hi_limits = np.array([10, 10, 10])


        wrapper = TWrapperClass(-bias[0], -bias[1])
        popt, pcov = curve_fit(wrapper.func, measured_xy_for_fit, target_xy_for_fit, p0, bounds=(low_limits, hi_limits))

        self._cal = CalibrationParameters(-bias[0], -bias[1], popt[0], popt[1], popt[2])
        self._have_cal = True
        return

def event_printer(event):
    """Helper function for exploring events.

    Prints all public attributes +
    """
    # capture the last event
    # global last_ev
    # last_ev = event
    for k, v in sorted(vars(event).items()):
        print(f'{k}: {v!r}')
    print('-'*25)


def on_key(event):
    # This is _super_ useful for debugging!
    print(event.key)

    # # if the key is c (any case)
    # if event.key.lower() == 'c':
    #     # change the color
    #     self.ln.set_color(next(self.color_cyle))

    #     # ask the GUI to re-draw the next time it can
    #     self.ln.figure.canvas.draw_idle()



# def main() -> None:
#     # Single input argument (optional) is filename to write output to.
#     parser = ArgumentParser()
#     parser.add_argument("filename")
#     args = parser.parse_args()
#     ana = CalibratorAnalyzer(fps=500, initial_size_sec=1800, increase_step_sec=300, before_sec=0.1, after_sec=0.1, vmax_px_per_sec=5000, doplot=True)

#     plt.ion()
#     g = FileEyeDataGenerator(args.filename)
#     for ed in g.generate():
#         ana.step(ed)
#     print("loop done")
#     plt.ioff()
#     plt.show()
#     #plt.pause(5)
#     #ana.ana_cr(0.1,0.1,5000,doplot=True)
    


# if __name__ == "__main__":
#     main()
