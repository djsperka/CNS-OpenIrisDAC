from pathlib import Path
from dac_common import CalibrationParameters, AnalogOutputPair, AnalogOutput
from open_iris_client import EyesData, Point
# from calibrator_analyzer import Calibrator
import os
from queue import Queue
#from platformdirs import PlatformDirs
import logging
import tomlkit
logger = logging.getLogger("GlobalState")

DAC_BACKEND = os.environ.get('DAC_BACKEND', 'dac')
if DAC_BACKEND == 'dac':
    # default - use local dac.py which supports both AIOUSB and (sort of) NI modules
    from dac import discover_ao_modules
elif DAC_BACKEND == 'nodac':
    from nodac import discover_ao_modules
else:
    raise RuntimeError(f'Cannot import dac module using DAC_BACKEND={DAC_BACKEND}. Expecting "dac" or "nodac".')


class GlobalState:
    def __init__(self, root_path:Path|None = None, current:str = 'default') -> None:
        if root_path is None:
            self.root_path = Path.home() / '.dpidac'
        else:
            self.root_path = root_path
        self.current = current
        logger.info(f"Config file: {self.config_file}")

        # assign non-config stuff first. 
        self.left_method = 'dpi'
        self.right_method = 'dpi'
        self.left_output = AnalogOutputPair()
        self.right_output = AnalogOutputPair()
        self.pupil_output = AnalogOutputPair()

        self.last_eyes_data = EyesData()
        self.is_running = False

        # for testing. When True, output taken from mouse position on main output graph
        self.is_mouse_mode = False
        self.mouse_mode_xy = Point(0,0)

        # count frames received
        self.frames_in = 0
        self.frames_start_time = 0.0  # time when first frame received
        
        # this stuff for calibration
        self.calibrating = False
        self.loading = False
        self.loading_filename = None
        self.calibration_plot_invalidated = True    # set this to True with calibration plots need updating
        self.calibration_diobits = int(0)
        self.calibration_fixation_x = 99999.9
        self.calibration_fixation_y = 99999.9
        self.calibration_recording = False
        self.calibration_frames_in = 0          # how many get pushed into queue
        self.calibration_frames_out = 0         # how many get popped from queue
        self.calibration_start_time = 0.0

        # these are parameters for the calibration analysis. 
        # TODO - add these to a settings file, and to GUI
        self.capture_fps:int=500
        self.calibration_initial_size_sec:int=1800
        self.calibration_increase_step_sec:int = 300
        self.calibration_queue:Queue=Queue()

        # load calibration 
        self.load_config()

        # see what kind of analog card we're using, prepare
        self.discover_analog_modules()

    @property
    def config_file(self):
        return self.root_path / self.current / 'config.toml'

    def maybe_create_config(self):
        if not self.root_path.exists():
            logger.info(f"Config folder {str(self.root_path)} does not exist. Creating...")
            self.root_path.mkdir(parents=True)
            logger.info("Config path created.")

        if not self.config_file.exists():
            logger.info(f"Config file {str(self.config_file)} does not exist, creating a new one")
            cfg = {}
            cfg['calibration']['before_sec'] = 0.1
            cfg['calibration']['after_sec'] =  0.1
            cfg['calibration']['vmax_px_per_sec'] = 5000
            cfg['calibration']['vpdx'] = 0.4
            cfg['calibration']['vpdy'] = 0.4
            cfg['calibration']['eye'] = 'Left'
            cfg['left']['CR'] = CalibrationParameters(-60,180,-.013,.013,0).to_dict()
            cfg['left']['DPI'] = CalibrationParameters(-60,180,-.013,.013,0).to_dict()
            cfg['left']['PUPIL'] = CalibrationParameters(0,0,3.0e-5,3.0e-5,0).to_dict()
            cfg['right']['CR'] = CalibrationParameters(80,180,-.013,.013,0).to_dict()
            cfg['right']['DPI'] = CalibrationParameters(80,180,-.013,.013,0).to_dict()
            cfg['right']['PUPIL'] = CalibrationParameters(0,0,3.0e-5,3.0e-5,0).to_dict()
            with self.config_file.open(mode='w') as fp:
                tomlkit.dump(cfg, fp)
            logger.info("Config file created")

    def load_config(self):

        # check if config path and file exist. If not, create them.
        self.maybe_create_config()

        # Now load file
        logger.info(f"Loading config file {str(self.config_file)}")
        with self.config_file.open(mode='r') as fp:
            cfg = tomlkit.load(fp)
        self.left_cal = CalibrationParameters.from_dict(cfg['left']['CR'])
        self.left_dpi = CalibrationParameters.from_dict(cfg['left']['DPI'])
        self.left_pupil_cal = CalibrationParameters.from_dict(cfg['left']['PUPIL'])
        self.right_cal = CalibrationParameters.from_dict(cfg['right']['CR'])
        self.right_dpi = CalibrationParameters.from_dict(cfg['right']['DPI'])        
        self.right_pupil_cal = CalibrationParameters.from_dict(cfg['right']['PUPIL'])
        self.calibration_before_sec = cfg['calibration']['before_sec']
        self.calibration_after_sec = cfg['calibration']['after_sec']
        self.calibration_vmax_px_per_sec = cfg['calibration']['vmax_px_per_sec']
        self.calibration_vpdx = cfg['calibration']['vpdx']
        self.calibration_vpdy = cfg['calibration']['vpdy']
        self.calibration_eye = cfg['calibration']['eye']

    def save_config(self):

        logger.info(f"Save config file {str(self.config_file)}")

        # build the cfg dict
        cfg = {}
        cfg['calibration']['before_sec'] = self.calibration_before_sec
        cfg['calibration']['after_sec'] =  self.calibration_after_sec
        cfg['calibration']['vmax_px_per_sec'] = self.calibration_vmax_px_per_sec
        cfg['calibration']['vpdx'] = self.calibration_vpdx
        cfg['calibration']['vpdy'] = self.calibration_vpdy
        cfg['calibration']['eye'] = self.calibration_eye
        cfg['left']['CR'] = self.left_cal.to_dict()
        cfg['left']['DPI'] = self.left_dpi.to_dict()
        cfg['left']['PUPIL'] = self.left_pupil_cal.to_dict()
        cfg['right']['CR'] = self.right_cal.to_dict()
        cfg['right']['DPI'] = self.right_dpi.to_dict()
        cfg['right']['PUPIL'] = self.right_pupil_cal.to_dict()
        with self.config_file.open(mode='w') as fp:
            tomlkit.dump(cfg, fp)
        logger.info(f"Config file {str(self.config_file)} saved.")


    def button_down(self, button:int):
        if button<0 or button>7:
            raise ValueError(f'Button must be between 0 and 7, got {button}')
        return self.calibration_diobits & (1 << button) != 0

    def discover_analog_modules(self):
        # TODO Move this to global state (also save serial numbers?)
        self.module_list = discover_ao_modules()
        logger.info(f"Found {len(self.module_list)} Output Devices: {self.module_list}")
        
        self.output_dict = {}
        for module in self.module_list:
            for channel in range(module.n_channels):
                key = f'{module.name}-ch{channel}'
                while key in self.output_dict:
                    key = key[:len(module.name)] + '-2' + key[len(module.name):]
                self.output_dict[key] = AnalogOutput(module, channel)

        logger.info(f"Found {len(self.output_dict)} Output Channels: {self.output_dict.keys()}")

    # def save(self, path:Path|None = None):
    #     if path is None:
    #         path = self.save_path

    #     if not path.exists():
    #         path.mkdir()
    #     # save calibrations
    #     self.left_cal.save(path / 'left_cal.txt')
    #     self.right_cal.save(path / 'right_cal.txt')
    #     self.pupil_cal.save(path / 'pupil_cal.txt')
    #     # save methods
    #     with open(path / 'methods.txt', 'w') as f:
    #         f.write(f'{self.left_method},{self.right_method}')
    
    # def load(self, path:Path|None = None):
    #     if path is None:
    #         path = self.save_path

    #     if not path.exists():
    #         logger.error(f'Folder for saving state {self.save_path} was not found.')
    #         return
    #     # load calibrations
    #     try:
    #         self.left_cal.load(path / 'left_cal.txt')
    #         self.right_cal.load(path / 'right_cal.txt')
    #         self.pupil_cal.load(path / 'pupil_cal.txt')
    #     except:
    #         logger.error('Error loading calibration files.')
    #     # load methods
    #     try:
    #         with open(path / 'methods.txt', 'r') as f:
    #             self.left_method, self.right_method = f.read().split(',')
    #         if self.left_method not in ['dpi', 'pcr']:
    #             self.left_method = 'dpi'
    #         if self.right_method not in ['dpi', 'pcr']:
    #             self.right_method = 'dpi'
    #     except:
    #         self.left_method = 'dpi'
    #         self.right_method = 'dpi'
