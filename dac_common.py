import numpy as np
from open_iris_client import Point
from dataclasses import dataclass
from pathlib import Path
import math

class AnalogModule:
    def __init__(self):
        self.name = None
        self.n_channels = 1
        self.v_max = 5
        self.v_min = -5
        self.v_out = np.zeros(self.n_channels)

    def write_channel(self, channel:int, voltage:float):
        self.v_out[channel] = voltage
        pass
    
    def write_channels(self, voltage:np.ndarray):
        """
        Writes a voltage to a channel. The voltage is clamped to the range [-v_max, v_max].
        """
        pass

    def __repr__(self) -> str:
        return f"AnalogModule(name={self.name}, n_channels={self.n_channels})"
    
    def __str__(self) -> str:
        return self.__repr__()


@dataclass
class CalibrationParameters:
    x_bias: float
    y_bias: float
    x_gain: float
    y_gain: float
    rotation: float

    def transform(self, pos:Point):
        return ((pos + Point(self.x_bias, self.y_bias)) * Point(self.x_gain, self.y_gain)).rotate(self.rotation * math.pi / 180)
    
    def save(self, fname:Path):
        with open(fname, 'w') as f:
            f.write(f'{self.x_bias},{self.y_bias},{self.x_gain},{self.y_gain},{self.rotation}')
    
    def load(self, fname:Path):
        try:
            with open(fname, 'r') as f:
                self.x_bias, self.y_bias, self.x_gain, self.y_gain, self.rotation = [float(x) for x in f.read().split(',')]
        except Exception as e:
            print(e)
            print('Error loading calibration file.')

class AnalogOutput:
    def __init__(self, module:AnalogModule = None, channel:int=0):
        if module is None:
            module = AnalogModule()
        self.module = module
        self.channel = channel
        self.out = 0
    
    def write(self, voltage:float):
        self.module.write_channel(self.channel, voltage)
        self.out = voltage

    @property
    def v_out(self):
        return self.module.v_out[self.channel]

class AnalogOutputPair:
    def __init__(self, output1:AnalogOutput|None=None, output2:AnalogOutput|None=None):
        if output1 is None:
            output1 = AnalogOutput()
        if output2 is None:
            output2 = AnalogOutput()
        self.output1 = output1
        self.output2 = output2
        self.out = Point(0,0)
    
    def write(self, voltage:Point):
        self.output1.write(voltage.x)
        self.output2.write(voltage.y)
        self.out = voltage

    @property
    def v_out(self):
        return Point(self.output1.v_out, self.output2.v_out)
