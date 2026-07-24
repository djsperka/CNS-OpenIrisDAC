import numpy as np 
from scipy.optimize import curve_fit as curve_fit
from open_iris_client import EyeData, EyesData, ExtraData, Point
from dac_common import CalibrationParameters
import math
import matplotlib.cm as cm
from dataclasses import dataclass
from argparse import ArgumentParser
from pathlib import Path
from generator import FileEyeDataGenerator
from matplotlib.backend_bases import MouseButton
from typing import List
from collections import defaultdict as defaultdict
import time
from threading import Thread
from queue import Queue
from globalstate import GlobalState
import logging

logger = logging.getLogger(__name__)

binding_id = None

def on_move(event):
    if event.inaxes:
        print(f'data coords {event.xdata} {event.ydata},',
              f'pixel coords {event.x} {event.y}')


def on_click(event):
    if event.button is MouseButton.LEFT:
        print(f'data coords {event.xdata} {event.ydata},',
              f'pixel coords {event.x} {event.y}')

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



class Calibrator(Thread):
    def __init__(self, gs:GlobalState, brecord:bool):
        super().__init__()
        self.globalstate = gs
        self._brecord = brecord
        self._stopnow = False
        self.initialize_calibration()

    def initialize_calibration(self):
        self._fps = self.globalstate.calibration_fps
        self._max_frames = np.floor(self.globalstate.calibration_initial_size_sec * self._fps)
        self._increase_step_frames = np.floor(self.globalstate.calibration_increase_step_sec * self._fps)
        self._nbefore = int(np.floor(self.globalstate.calibration_before_sec * self._fps))
        self._nafter = int(np.floor(self.globalstate.calibration_after_sec * self._fps))
        self._vmax = self.globalstate.calibration_vmax_px_per_sec/self._fps

        # data arrays
        self._pupil_xy=np.zeros((2,self._max_frames))
        self._cr_xy=np.zeros((2,self._max_frames))
        self._p4_xy=np.zeros((2,self._max_frames))
        self._pupil_xy=np.zeros((2,self._max_frames))
        self._pupil_xy=np.zeros((2,self._max_frames))

        # good measurements saved here
        self._meas = defaultdict(list)
        self._invalidated = True
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
        self._invalidated = True   # re-draw without the resultant points

    def run(self):

        # loop over this cycle until we're told to stop
        while True:

            # wait for globalstate to say we're calibrating. 
            # we could get stopped while waiting, though, so take care of that.
            while not self.globalstate.calibrating and not self._stopnow:
                time.sleep(0.1)

            if self._stopnow:
                break

            # Initialize
            self.initialize_calibration()
            self._invalidated = True

            # watch the queue, and watch for stopping
            logger.info("Calibrator - filling queue...")
            while not self._stopnow:
                if not self.globalstate.calibration_queue.empty():
                    self.step(self.globalstate.calibration_queue.get())
                else:
                    time.sleep(0.1)
            logger.info(f"stopnow is set:  received {self.counter}")
        logger.info(f"Thread ending.")

    @property
    def measurements(self):
        return self._meas

    @property
    def invalidated(self):
        return self._invalidated

    @invalidated.setter
    def invalidated(self, v:bool):
        self._invalidated = v

    @property
    def counter(self):
        return self._counter

    def step(self, ed: EyesData):
        data_ok = True
        if ed.left.pupil.x == 0 or ed.left.pupil.y == 0:
            self._pupil_xy[:, self._counter] = np.nan
            data_ok = False
        else:
            self._pupil_xy[0, self._counter] = ed.left.pupil.x
            self._pupil_xy[1, self._counter] = ed.left.pupil.y

        if ed.left.cr.x == -100 or ed.left.cr.y == -100:
            self._cr_xy[:, self._counter] = np.nan
            data_ok = False
        else:
            self._cr_xy[0, self._counter] = ed.left.cr.x
            self._cr_xy[1, self._counter] = ed.left.cr.y

        if ed.left.p4.x == 820 or ed.left.p4.y == -100:
            self._p4_xy[:, self._counter] = np.nan
            data_ok = False
        else:
            self._p4_xy[0, self._counter] = ed.left.p4.x
            self._p4_xy[1, self._counter] = ed.left.p4.y
            
        button_is_pressed = ed.extra.ints[8] & 0x1
        framesig_present = ed.extra.ints[0] & 0x1

        if not self._framesig_on:
            if framesig_present:
                self._framesig_on_at = self._counter
                self._framesig_on = True
        else:
            # framesig_on is True, meaning the last time through the FRAME signal was present.
            # We only need to check if framesig is not present this time.
            if not framesig_present:
                self._framesig_on = False

        if self._button_up:
            if button_is_pressed:
                self._button_up = False
                if data_ok:
                    self._button_list.append(ButtonPressInfo(self._counter, ed.extra.doubles[7], ed.extra.doubles[8], self._framesig_on_at, False))

        else:
            if not button_is_pressed:
                self._button_up = True
    
        self._counter += 1        
        self._button_ana()
        return self._counter

    def get_crsig(self, start:None|int=None, stop:None|int=None, step:None|int=None):
        """Get CR signal (cr-pupil) for the slice described by slice(start,stop,step). 

        Args:
            start (None | int, optional): see slice(). Defaults to None.
            stop (None | int, optional): see slice(). Defaults to None.
            step (None | int, optional): see slice(). Defaults to None.

        Returns:
            ndarray: row 0/1 is x/y value. shape=(2,M)
        """
        s=slice(start,stop,step)
        return self._cr_xy[:,s]-self._pupil_xy[:,s]

    def get_dpisig(self, start:None|int=None, stop:None|int=None, step:None|int=None):
        s=slice(start, stop, step)
        return self._cr_xy[:,s]-self._p4_xy[:,s]

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
                        crsig = self.get_crsig(binf.ind-self._nbefore, binf.ind+self._nafter)
                        if self._check_velocity(crsig, self._vmax):
                            m = crsig.mean(axis=1)
                            self._meas[(binf.vx,binf.vy)].append(m)
                            self._invalidated = True
                        binf.checked = True
                else:
                    binf.checked = True # weird initialization values here

    def dofit(self):
        # The items in the measurements dict are lists. Each list element
        # is a numpy ndarray with shape (2,) - this is the (x,y) of that crsig measurement. 
        # The stim position is in the key, which is a tuple (stimx, stimy)

        target_xy_list=[]
        measured_xy_list = []
        bias = (0,0)
        for i, (key,pts) in enumerate(self._meas.items()):
            if key == (0,0):
                # get the mean of these - this is the bias
                bias = np.stack(pts).mean(axis=0)
                logger.info(f"Used {len(pts)} to get bias: {bias}")
            else:
                for xy in pts:
                    target_xy_list.append(key)
                    measured_xy_list.append(xy)

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
        self._invalidated = True
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



def main() -> None:
    # Single input argument (optional) is filename to write output to.
    parser = ArgumentParser()
    parser.add_argument("filename")
    args = parser.parse_args()
    ana = CalibratorAnalyzer(fps=500, initial_size_sec=1800, increase_step_sec=300, before_sec=0.1, after_sec=0.1, vmax_px_per_sec=5000, doplot=True)

    plt.ion()
    g = FileEyeDataGenerator(args.filename)
    for ed in g.generate():
        ana.step(ed)
    print("loop done")
    plt.ioff()
    plt.show()
    #plt.pause(5)
    #ana.ana_cr(0.1,0.1,5000,doplot=True)
    


if __name__ == "__main__":
    main()
