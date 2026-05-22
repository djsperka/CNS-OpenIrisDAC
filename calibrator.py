import serial
import os
#assert os.name == 'nt', 'DAC only works on Windows'
import AIOUSB as ao

class Calibrator:
    def __init__(self, port):
        self.ser = serial.Serial(port, baudrate=115200, timeout=1)

    def command(self, cmd: str):
        self.ser.write((cmd + '\n').encode())

    def get_response(self):
        response = self.ser.readline().decode().strip()
        return response.split(' ', 2)

    def parse_response(self, response):
        a, b, t_str = response.split(' ', 2)
        if a != 'response' or b != 'calibrate':
            raise RuntimeError(f"Unexpected response: {response}")
        return float(t_str)

    def calibrate(self) -> float:
        self.command('calibrate')
        t = None
        while t is None:
            response = self.ser.readline().decode().strip()