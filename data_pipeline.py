from globalstate import GlobalState
from generator import FakeEyeDataGenerator, OpenIrisClientGenerator
from shared_resources import in_cal_lock
from open_iris_client import Point
import time

class DataPipeline:
    def __init__(self, state:GlobalState, fake: bool=False, server_address: str='localhost', port: int=9003, output: str='', fake_file: str='', cal_recording_path=None):
        self.state = state
        self.server_address = server_address
        self.port = port
        self.fake = fake        
        self.output = output
        self.output_file = None
        self.fake_file = fake_file
        self.cal_recording_path = cal_recording_path
        self.cal_recording_fd = None

    def run(self, debug=False):

        # create generator
        if self.fake:
            generator = FakeEyeDataGenerator(self.state, self.fake_file)
        else:  
            generator = OpenIrisClientGenerator(self.state, self.server_address, self.port)

        for data in generator.generate():    
            self.state.last_eyes_data = data
            if not self.state.frames_start_time:
                self.state.frames_start_time = time.monotonic()
            self.state.frames_in += 1

            if self.state.calibrating:
                # Assign values for current calibration stuff. 
                if not self.fake or (self.fake and not self.fake_file):
                    # assign dio bits to data.extra.ints[8] 
                    data.extra.ints[8] = self.state.calibration_diobits
                    data.extra.doubles[5] = self.state.calibration_vpdx
                    data.extra.doubles[6] = self.state.calibration_vpdy
                    data.extra.doubles[7] = self.state.calibration_fixation_x
                    data.extra.doubles[8] = self.state.calibration_fixation_y
                # put the EyesData into the queue - it will get picked up by the calibration thread
                self.state.calibration_queue.put(data)
                with in_cal_lock:
                    self.state.calibration_frames_in += 1

            # transform current signal and write to appropriate output
            if not self.state.is_mouse_mode:
                left_output = data.left.cr - (data.left.pupil if self.state.left_method == 'pcr' else data.left.p4)
                left_output = self.state.left_cal.transform(left_output)
                self.state.left_output.write(left_output)
            else:
                self.state.left_output.write(self.state.mouse_mode_xy)
            
            right_output = data.right.cr - (data.right.pupil if self.state.right_method == 'pcr' else data.right.p4)
            right_output = self.state.right_cal.transform(right_output)
            self.state.right_output.write(right_output)

            pupil_output = Point(data.left.pupil_area, data.right.pupil_area)
            pupil_output = self.state.pupil_cal.transform(pupil_output)
            self.state.pupil_output.write(pupil_output)
            if debug:
                print(data)
                print(f'{right_output}, {pupil_output}')
