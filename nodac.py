
import numpy as np
from dac_common import AnalogModule, AnalogOutput, AnalogOutputPair, CalibrationParameters


# These are to replace AIO calls in diothread
diOnly = 1
def DIO_Read8():
    return 0,0


class FakeModule:
    def __init__(self, verbose:bool=False):
        self.name = 'FakeModule'
        self.n_channels = 4
        self.v_max = 5
        self.v_min = -5
        self.v_out = np.zeros(self.n_channels)
        self.verbose = verbose

    def write_channel(self, channel:int, voltage:float):
        self.v_out[channel] = voltage
        if self.verbose:
            print(f'Writing {voltage} to channel {channel}')
    
    def write_channels(self, voltages:np.ndarray):
        """
        Writes a voltage to a channel. The voltage is clamped to the range [-v_max, v_max].
        """
        assert voltages.shape == (self.n_channels,), f'Expected {self.n_channels} channels, got {voltages.shape[0]}'
        v_out = np.clip(voltages, self.v_min, self.v_max)
        for i in range(self.n_channels):
            if self.verbose:
                print(f'Writing {voltages[i]} to channel {i}')
        self.v_out = v_out

    def __repr__(self) -> str:
        return f"AnalogModule(name={self.name}, n_channels={self.n_channels})"
    
    def __str__(self) -> str:
        return self.__repr__()




def discover_ao_modules():
    """
    Returns a list of fake modules connected to the computer.
    """
    ao_modules = [FakeModule()]
    return ao_modules
    
if __name__ == "__main__":
    ao_idx = discover_ao_modules()
    print(ao_idx)
    print('Done!')
