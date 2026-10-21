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

    root_path = Path.home() / '.dpidac'     # configuration folders/files ALWAYS located in this folder. 
    default_subject = 'default'
    default_basename = 'config'

    def __init__(self, subject:str = 'default', basename:str = 'config') -> None:
        if not subject:
            subject = self.default_subject
        if not basename:
            basename = self.default_basename

        self.subject = subject
        self.basename = basename

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

        # These are parameters from the config file. Create default/dummy values here, will be overwritten
        # by loaded config file. If no config file exists, these values will be written to a new config file.
        self.left_cal = CalibrationParameters(-60,180,-.013,.013,0)
        self.left_dpi = CalibrationParameters(-60,180,-.013,.013,0)
        self.pupil_cal = CalibrationParameters(0,0,3.0e-5,3.0e-5,0)
        self.right_cal = CalibrationParameters(-60,180,-.013,.013,0)
        self.right_dpi = CalibrationParameters(-60,180,-.013,.013,0)        
        self.calibration_before_sec = 0.1
        self.calibration_after_sec = 0.1
        self.calibration_vmax_px_per_sec = 5000
        self.calibration_vpdx = 0.4
        self.calibration_vpdy = 0.4
        self.calibration_eye = 'Left'

        # load calibration 
        self.load_config()

        # see what kind of analog card we're using, prepare
        self.discover_analog_modules()

    @property
    def config_file(self):
        return GlobalState.root_path / self.subject / f"{self.basename}.toml"

    @classmethod
    def select_subject(cls):
        import PySimpleGUI as sg
        subjects = next(os.walk(str(cls.root_path)))[1]
        window = sg.Window('Select subject',
            [[sg.Text('Select subject')],
            [sg.Listbox(subjects, key='-SUBJECTS-', select_mode=sg.LISTBOX_SELECT_MODE_SINGLE, size=(15,5), enable_events=True, default_values=['default']),],
            [sg.OK(), sg.Cancel()]
        ])

        while True:
            event, values = window.read(timeout=100) # 20ms = 50Hz
            # if event != '__TIMEOUT__':
            #     print(event, values)
            # handle exit
            if event == sg.WIN_CLOSED or event == 'OK' or event == 'Cancel':
                break

        window.close()
        return None if event != 'OK' else values['-SUBJECTS-'][0]

    def maybe_create_config(self):
        """Check if config file (expected to be at root_path/subject/basename.toml)
        exists. If not, create it (and folder if it doesn't exist). 
        If it does exist, do nothing and return.
        """
        save_path = GlobalState.root_path / self.subject
        if not save_path.exists():
            logger.info(f"Config folder {str(save_path)} does not exist. Creating...")
            save_path.mkdir(parents=True)

        if not self.config_file.exists():
            logger.info(f"Config file {str(self.config_file)} does not exist, creating a new one")
            self.save_config()

    def load_config(self, subject:str = '', basename: str = ''):
        """Load configuration file and update state variables. If subject or basename is provided, use those to find config file. If file or folder does not yet exist, create it/them.

        Args:
            subject (str, optional): Subject folder to load from. Defaults to '' - current subject will be used.
            basename (str, optional): Config file basename. Defaults to '' - current basename will be used.
        """

        # if args not passed, load using current values
        if subject:
            print(f"subject {subject}")
            self.subject = subject
        if basename:
            print(f"basename {basename}")
            self.basename = basename

        # check if config path and file exist. If not, create them.
        self.maybe_create_config()

        # Now load file
        logger.info(f"Loading config file {str(self.config_file)}")
        with self.config_file.open(mode='r') as fp:
            cfg = tomlkit.load(fp)
        self.left_cal = CalibrationParameters.from_dict(cfg['left.CR'])
        self.left_dpi = CalibrationParameters.from_dict(cfg['left.DPI'])
        self.pupil_cal = CalibrationParameters.from_dict(cfg['both.PUPIL'])
        self.right_cal = CalibrationParameters.from_dict(cfg['right.CR'])
        self.right_dpi = CalibrationParameters.from_dict(cfg['right.DPI'])        
        self.calibration_before_sec = cfg['calibration']['before_sec']
        self.calibration_after_sec = cfg['calibration']['after_sec']
        self.calibration_vmax_px_per_sec = cfg['calibration']['vmax_px_per_sec']
        self.calibration_vpdx = cfg['calibration']['vpdx']
        self.calibration_vpdy = cfg['calibration']['vpdy']
        self.calibration_eye = cfg['calibration']['eye']

    def save_config(self):

        # build the cfg object
        cfg = tomlkit.document()
        calibration = tomlkit.table()
        calibration.add('before_sec', self.calibration_before_sec)
        calibration.add('after_sec', self.calibration_after_sec)
        calibration.add('vmax_px_per_sec', self.calibration_vmax_px_per_sec)
        calibration.add('vpdx', self.calibration_vpdx)
        calibration.add('vpdy', self.calibration_vpdy)
        calibration.add('eye', self.calibration_eye)
        cfg.add('calibration', calibration)
        cfg.add('left.CR', self.left_cal.to_table())
        cfg.add('left.DPI', self.left_dpi.to_table())
        cfg.add('both.PUPIL', self.pupil_cal.to_table())
        cfg.add('right.CR', self.right_cal.to_table())
        cfg.add('right.DPI', self.right_dpi.to_table())

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


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO)

    # Single input argument (optional) is filename to write output to.
    parser = argparse.ArgumentParser()
    parser.add_argument("--subject", help="Current subject/config to use.", type=str, default='')
    parser.add_argument("--basename", help="Basename for config file (no dot or extension)", type=str, default='')
    args = parser.parse_args()

    gs = GlobalState(subject=args.subject, basename=args.basename)
    gs.save_config()