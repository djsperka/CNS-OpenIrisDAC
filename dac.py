import os
assert os.name == 'nt', 'DAC only works on Windows'
import numpy as np
from dac_common import AnalogModule, AnalogOutput, AnalogOutputPair, CalibrationParameters
has_aio = False
try:
    import AIOUSB as ao
    has_aio = True
except Exception as e:
    print('Error importing AIOUSB. Ignore if using NI modules.')
    print(e)

has_daqmx = False
try:
    import nidaqmx
    import nidaqmx.stream_writers
    import nidaqmx.system
except Exception as e:
    print('Error importing nidaqmx. Ignore if using AIOUSB.')
    print(e)

def discover_ni_modules():
    """
    Returns a list of NI modules connected to the computer.
    """
    if not has_daqmx:
        return []

    system = nidaqmx.system.System.local()
    return system.devices


class NIModule(AnalogModule):
    pass

class AIOModule(AnalogModule):
    """Wrapper for AIOUSB module."""
    def __init__(self, index):
        self.index = index
        _,self.pid,self.name,_,_ = ao.QueryDeviceInfo(self.index)
        self.serial = ao.GetDeviceSerialNumber(self.index)

        # (n_channels, bitdepth)
        self.metadata_dict = {
            'USB-AO16-16A' : (16, 16),
            'USB-AO16-16E' : (16, 16),
            'USB-AO12-16A' : (16, 12),
            'USB-AO12-16E' : (16, 12),
            'USB-AO16-8E' : (8, 16),
            'USB-AO16-8A' : (8, 16),
            'USB-AO12-8E' : (8, 12),
            'USB-AO12-8A' : (8, 12),
            'USB-AO16-4A' : (4, 16),
            'USB-AO16-4E' : (4, 16),
        }

        self.n_channels = self.metadata_dict[self.name][0]
        self.bitdepth = self.metadata_dict[self.name][1]
        self.v_max = 5
        self.v_min = -5
        self.v_out = np.zeros(self.n_channels)
        self.enable()
        self.write_channels(self.v_out)

    def enable(self):
        ao.DACSetBoardRange(ao.diOnly, 1)
    
    def disable(self):
        ao.DACSetBoardRange(ao.diOnly, 0)

    def write_channel(self, channel:int, voltage:float):
        """
        Writes a voltage to a channel. The voltage is clamped to the range [-v_max, v_max].
        """
        v_out = np.clip(voltage, self.v_min, self.v_max)
        short_out = int((v_out + self.v_max) / self.v_max / 2 * (2**self.bitdepth))
        ao.DACDirect(self.index, channel, short_out)
        self.v_out[channel] = v_out

    def write_channels(self, voltages:np.ndarray):
        """
        Writes a voltage to a channel. The voltage is clamped to the range [-v_max, v_max].
        """
        assert voltages.shape == (self.n_channels,), f'Expected {self.n_channels} channels, got {voltages.shape[0]}'
        v_out = np.clip(voltages, self.v_min, self.v_max)
        short_out = np.array((v_out + self.v_max) / self.v_max / 2 * (2**self.bitdepth), dtype=np.uint16)
        for i in range(self.n_channels):
            ao.DACDirect(self.index, i, short_out[i])
        self.v_out = v_out
    

def discover_ao_modules():
    """
    Returns a list of AIOUSB modules connected to the computer.
    """
    if not has_aio:
        return []
    
    bitmask = ao.GetDevices()
    ao_list = []
    for i in range(8):
        if bitmask & (1 << i):
            ao_list.append(i)

    ao_modules = [AIOModule(idx) for idx in ao_list]
    return ao_modules
    
if __name__ == "__main__":
    ao_idx = discover_ao_modules()
    print(ao_idx)
    print('Done!')
