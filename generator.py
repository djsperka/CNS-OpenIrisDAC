from globalstate import GlobalState
from open_iris_client import OpenIrisClient, EyesData
import time
import pickle
import math
import logging

logger = logging.getLogger(__name__)

class EyeDataGenerator:
    def __init__(self, state:GlobalState):
        self.state = state

    def generate(self):
        pass


fake_data = {
    'Left': {
        'FrameNumber': 9683, 
        'Pupil': {
            'Center': {
                'X': 347.87344, 
                'Y': 211.9014
                }, 
            'Size': {
                'Width': 17.5, 
                'Height': 6.16
                }
            }, 
        'CRs': [{'X': -100, 'Y': -100}, {'X': 820, 'Y': -100}, {'X': 820, 'Y': 820}, {'X': -100, 'Y': 820}]}, 
        'Right': {'FrameNumber': 0, 'Pupil': {'Center': {'X': 0, 'Y': 0}, 'Size': {'Width': 0, 'Height': 0}}, 'CRs': []}, 
        'Extra': {'Ints': [12, 0, 0, 0, 0, 0, 0, 0, 0], 'Doubles': [0, 0, 0, 0, 0, 0, 0, 0, 0]}}


class FakeEyeDataGenerator(EyeDataGenerator):
    def __init__(self, state:GlobalState, fake_calfilename:str=''):
        super().__init__(state)
        self.t = 0
        self.fake_calf = None
        self.fake_calfilename = fake_calfilename

    def _makefakedata(self, t):
        """Generate a EyeData struct with pupil and CR location set so the "eye" orbits the origin at a fixed radius.

        Args:
            t (int): frame number to assign to fake data

        Returns:
            EyeData: Enough of the dict to pass to EyesData()
        """

        fake_data['Left']['FrameNumber'] = t
        theta = self.t*math.pi/500
        r = 15
        fake_data['Left']['Pupil']['Center']['X'] = 0
        fake_data['Left']['Pupil']['Center']['Y'] = 0
        fake_data['Left']['CRs'][0]['X'] = r*math.cos(theta)
        fake_data['Left']['CRs'][0]['Y'] = r*math.sin(theta)
        return fake_data

    def generate(self):
        while self.state.is_running:
            if not self.state.calibrating:
                data = EyesData(self._makefakedata(self.t))
                yield data
            else:
                if not self.fake_calf:
                    logger.info(f"Switch to calibration fake data from file {self.fake_calfilename}")
                    self.fake_calf = open(self.fake_calfilename,'rb')
                try:
                    ed = pickle.load(self.fake_calf)
                    yield ed
                except EOFError:
                    # done calibrating - change state and close this generator
                    close(self.fake_calf)
                    self.fake_calf = None
                    logger.info(f"Fake calibration data done.")
                    self.state.calibrating = False
                    data = EyesData(self._makefakedata(self.t))
                    yield data

            self.t += 1
            time.sleep(0.001)

class OpenIrisClientGenerator(EyeDataGenerator):
    def __init__(self, state:GlobalState, server_address='localhost', port=9003):
        super().__init__(state)
        self.server_address = server_address
        self.port = port

    def generate(self):
        with OpenIrisClient(self.server_address, self.port) as client:
            while self.state.is_running:
                data = client.fetch_next_data()
                yield data

class FileEyeDataGenerator(EyeDataGenerator):
    def __init__(self, filename):
        self._filename = filename

    def generate(self):        
        with open(self._filename,'rb') as f:
            while True:
                try:
                    ed = pickle.load(f)
                    yield ed
                except EOFError:
                    break       
