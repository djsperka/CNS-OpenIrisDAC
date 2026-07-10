import numpy as np 
from scipy.optimize import curve_fit as curve_fit
from open_iris_client import EyeData, EyesData, ExtraData, Point
from dac_common import CalibrationParameters
import math

class TWrapperClass:

    def __init__(self, x_bias, y_bias):
        self.cal = CalibrationParameters(x_bias=x_bias, y_bias=y_bias,x_gain=1,y_gain=1,rotation=0)
    
    def do_transform(self, xy, x_gain, y_gain, degrees):
        self.cal.x_gain = x_gain
        self.cal.y_gain = y_gain
        self.cal.rotation = degrees
        p = self.cal.transform(Point(xy[0], xy[1]))
        # xy is an avg x,y crsig values
        # return nd.array[xtrans,ytrans] from transform using params   
        p = Point(xy[0] * x_gain, xy[1] * y_gain)
        trans = p.rotate(degrees * math.pi / 180)
        #print(f"xy {xy[0]},{xy[1]} {x_gain} {y_gain} {degrees} trans {trans.x},{trans.y}")
        return np.array([trans.x, trans.y])


    def func(self, xydata, x_gain, y_gain, degrees):
        pdata = np.apply_along_axis(self.do_transform, 0, xydata, x_gain, y_gain, degrees)
        print(pdata)
        return pdata.ravel()



class CalibratorAnalyzer():
    def __init__(self, fps:int=500, initial_size_sec:int=1800, increase_step_sec:int = 300):
        self._fps = fps
        self._max_frames = np.floor(initial_size_sec * fps)
        self._increase_step_frames = np.floor(increase_step_sec * fps)

        # data arrays
        self._pupil_xy=np.zeros((2,self._max_frames))
        self._cr_xy=np.zeros((2,self._max_frames))
        self._p4_xy=np.zeros((2,self._max_frames))
        self._pupil_xy=np.zeros((2,self._max_frames))
        self._pupil_xy=np.zeros((2,self._max_frames))
        
        # these are for state management
        self._counter = 0
        self._button_up = True
        self._button_list=[]  # (index,x,y)
        self._framesig_on = False
        self._framesig_on_at = 0

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
                    self._button_list.append((self._counter, ed.extra.doubles[7], ed.extra.doubles[8], self._framesig_on_at))
        else:
            if not button_is_pressed:
                self._button_up = True
    
        self._counter += 1        
        return self._counter

    def get_crsig(self):
        return self._cr_xy[:,:self._counter]-self._pupil_xy[:,:self._counter]

    def get_dpisig(self):
        return self._cr_xy[:,:self._counter]-self._p4_xy[:,:self._counter]


    def _check_velocity(self, xy, ind, nbefore, nafter, vmax):
        """Check that velocity (in x and y separately) is less than vmax in the range defined by ind, nbefore, and nafter.

        Args:
            xy (numpy array nframes x 2): xy values
            ind (int): index of button press
            nbefore (int): nframes before button press to include in tests
            nafter (int): nframes after button press blah blah
            vmax (float): max velocity 
        """
        v = np.diff(xy, axis=1)
        return np.all(np.abs(v[:,ind-nbefore:ind+nafter]) < vmax)



    def ana_cr(self, before_sec:float=0.1, after_sec:float=0.1, vmax_px_per_sec:float=5000):
        nbefore = int(np.floor(before_sec * self._fps))
        nafter = int(np.floor(after_sec * self._fps))
        vmax = vmax_px_per_sec/self._fps

        measured_xy_list=[] # tuples of xav,yav,xv,yv for good trials
        bias_xy_list = []
        target_xy_list=[]
        crsig = self.get_crsig()

        for (ind,vx,vy,f) in self._button_list:
            if ind+nafter < self._counter:
                if self._check_velocity(crsig,ind,nbefore,nafter,vmax):
                    # save (0,0) separately - this will be offset value
                    m = np.mean(crsig[:,ind-nbefore:ind+nafter], axis=1)
                    if vx==0 and vy==0:
                        bias_xy_list.append(m)
                    else:
                        measured_xy_list.append(m)
                        target_xy_list.append((vx, vy))

        bias = np.stack(bias_xy_list).mean(axis=0)
        xdata=(np.stack(measured_xy_list)).T
        ydata=np.stack(target_xy_list).ravel()

        # initial guess for x_gain, y_gain, degrees
        p0 = np.array([.2,.2,0])

        # limits for same
        low_limits = np.array([0.1, 0.1, -90])
        hi_limits = np.array([20, 20, 90])

        # fit
        wrapper = TWrapperClass(-bias[0], -bias[1])
        popt, pcov = curve_fit(wrapper.func, xdata, ydata, p0, bounds=(low_limits, hi_limits))
        print("popt",popt)
        print("pcov",pcov)

# # get transform of input data, plot it
# pdata = transform_wrapper(xdata, popt[0], popt[1], popt[2])
# print(f"pdata shape {np.shape(pdata)}")
# result = pdata.reshape((2,pdata.shape[0]//2))
# print(np.shape(result))
# print(np.shape(xdata))



# f, axes = plt.subplots(2, 1, figsize=(10,10))
# axes[0].scatter(xdata[0,:], xdata[1,:], color='blue', label='raw')
# axes[0].set_xlabel('X')
# axes[0].set_ylabel('Y')
# axes[0].set_title('Raw CR signal')
# axes[1].scatter(result[0,:], result[1,:], color='blue', label='transformed')
# axes[1].set_xlabel('X')
# axes[1].set_ylabel('Y')
# f.tight_layout()
# plt.show()




def main() -> None:
    from generator import FileEyeDataGenerator
    filename='./cal95.pkl'
    ana = CalibratorAnalyzer()
    g = FileEyeDataGenerator(filename)
    for ed in g.generate():
        ana.step(ed)
    print(f"crsig shape {str(np.shape(ana.get_crsig()))}")
    ana.ana_cr(0.1,0.1,5000)
    #print(measured_xy)
    #print(target_xy)



if __name__ == "__main__":
    main()
