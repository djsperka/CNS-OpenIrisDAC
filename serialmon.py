from serial import Serial
from gui import GlobalState
from time import sleep

class SerialMonitor:
    def __init__(self, state:GlobalState, comport:str=''):
        self.state = state
        self.comport = comport
        self.ser:Serial|None = None
        self.baudrate = 115200

    def run(self):
        # open port or fail
        self.ser = Serial(self.comport, baudrate=self.baudrate, timeout=0.01)
        while self.state.is_running:
            # check if anything waiting to be read
            while self.ser.in_waiting:
                s=self.ser.readline()
                print("Got input {s}")

            # chill
            sleep(.05)

    def __del__(self):
        if self.ser and self.ser.is_open:
            self.ser.close()
