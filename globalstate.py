from pathlib import Path
from dac_common import CalibrationParameters, AnalogOutputPair, AnalogOutput
from open_iris_client import EyesData, Point
import os
from queue import Queue
from platformdirs import PlatformDirs

DAC_BACKEND = os.environ.get('DAC_BACKEND', 'dac')
if DAC_BACKEND == 'dac':
    # default - use local dac.py which supports both AIOUSB and (sort of) NI modules
    from dac import discover_ao_modules
elif DAC_BACKEND == 'nodac':
    from nodac import discover_ao_modules
else:
    raise RuntimeError(f'Cannot import dac module using DAC_BACKEND={DAC_BACKEND}. Expecting "dac" or "nodac".')


class GlobalState:
    def __init__(self, root_dir:Path|None = None) -> None:
        if root_dir is None:
            root_path = PlatformDirs("CNS-OpenIrisDAC", appauthor=False).user_config_path
        self.save_path = root_path / 'cals' / '.state'
        self.save_path.mkdir(exist_ok=True, parents=True)
        self.data_path = root_path / 'cals' / 'data'
        self.data_path.mkdir(exist_ok=True, parents=True)

        self.left_cal = CalibrationParameters(-60,180,-.013,.013,0)
        self.left_method = 'dpi'
        self.left_output = AnalogOutputPair()

        self.right_cal = CalibrationParameters(80,180,-.013,.013,0)
        self.right_method = 'dpi'
        self.right_output = AnalogOutputPair()

        self.pupil_cal = CalibrationParameters(0,0,3e-5,3e-5,0)
        self.pupil_output = AnalogOutputPair()

        self.last_eyes_data = EyesData()
        self.is_running = True

        # for testing. When True, output taken from mouse position on main output graph
        self.is_mouse_mode = False
        self.mouse_mode_xy = Point(0,0)

        # this stuff for calibration
        self.calibrating = False
        self.loading = False
        self.loading_filename = None
        self.calibration_plot_invalidated = True    # set this to True with calibration plots need updating
        self.calibration_diobits = int(0)
        self.calibration_vpdx = 0.4
        self.calibration_vpdy = 0.4
        self.calibration_fixation_x = 99999.9
        self.calibration_fixation_y = 99999.9
        self.calibration_recording = False

        # these are parameters for the calibration analysis. 
        # TODO - add these to a settings file, and to GUI
        self.calibration_fps:int=500
        self.calibration_initial_size_sec:int=1800
        self.calibration_increase_step_sec:int = 300
        self.calibration_before_sec:float=0.1
        self.calibration_after_sec:float=0.1
        self.calibration_vmax_px_per_sec:float=5000
        self.calibration_queue:Queue=Queue()
        self.calibrator=None

        # load calibration 
        self.load()

        # see what kind of analog card we're using, prepare
        self.discover_analog_modules()

    def button_down(self, button:int):
        if button<0 or button>7:
            raise ValueError(f'Button must be between 0 and 7, got {button}')
        return self.calibration_diobits & (1 << button) != 0

    def discover_analog_modules(self):
        # TODO Move this to global state (also save serial numbers?)
        self.module_list = discover_ao_modules()
        print(f"Found {len(self.module_list)} Output Devices: {self.module_list}")
        
        self.output_dict = {}
        for module in self.module_list:
            for channel in range(module.n_channels):
                key = f'{module.name}-ch{channel}'
                while key in self.output_dict:
                    key = key[:len(module.name)] + '-2' + key[len(module.name):]
                self.output_dict[key] = AnalogOutput(module, channel)

        print(f"Found {len(self.output_dict)} Output Channels: {self.output_dict.keys()}")

    def save(self, path:Path|None = None):
        if path is None:
            path = self.save_path

        if not path.exists():
            path.mkdir()
        # save calibrations
        self.left_cal.save(path / 'left_cal.txt')
        self.right_cal.save(path / 'right_cal.txt')
        self.pupil_cal.save(path / 'pupil_cal.txt')
        # save methods
        with open(path / 'methods.txt', 'w') as f:
            f.write(f'{self.left_method},{self.right_method}')
    
    def load(self, path:Path|None = None):
        if path is None:
            path = self.save_path

        if not path.exists():
            print('No save directory found.')
            return
        # load calibrations
        try:
            self.left_cal.load(path / 'left_cal.txt')
            self.right_cal.load(path / 'right_cal.txt')
            self.pupil_cal.load(path / 'pupil_cal.txt')
        except:
            print('Error loading calibration files.')
        # load methods
        try:
            with open(path / 'methods.txt', 'r') as f:
                self.left_method, self.right_method = f.read().split(',')
            if self.left_method not in ['dpi', 'pcr']:
                self.left_method = 'dpi'
            if self.right_method not in ['dpi', 'pcr']:
                self.right_method = 'dpi'
        except:
            self.left_method = 'dpi'
            self.right_method = 'dpi'
