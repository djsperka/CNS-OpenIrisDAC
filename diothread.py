from threading import Thread, Event
from AIOUSB import diOnly, DIO_Read8
from shared_resources import ao_lock
from gui import GlobalState

# Source - https://stackoverflow.com/a/12435256
# Posted by Hans Then, modified by community. See post 'Timeline' for change history
# Retrieved 2026-06-02, License - CC BY-SA 3.0

class DIOThread(Thread):
    def __init__(self, event: Event, state: GlobalState, twait: float = 0.01):
        Thread.__init__(self)
        self.stopped = event
        self.state = state
        self.twait = twait

    def run(self):
        while not self.stopped.wait(self.twait):
            with ao_lock:
                status, v = DIO_Read8(diOnly, 0)                
            if status != 0:
                print(f'Error reading DIO: {status}')
            else:
                self.state.calibration_diobits = v



