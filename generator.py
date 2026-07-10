from globalstate import GlobalState
from open_iris_client import OpenIrisClient, EyesData
import time
import pickle

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
    def __init__(self, state:GlobalState):
        super().__init__(state)
        self.t = 0

    def generate(self):
        while self.state.is_running:
            fake_data['Left']['FrameNumber'] = self.t
            data = EyesData(fake_data)
            yield data
            self.t += 1
            time.sleep(0.1)

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
