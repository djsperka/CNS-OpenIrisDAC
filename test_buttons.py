from globalstate import GlobalState
from threading import Event
from diothread import DIOThread
import time
import logging

logger = logging.getLogger("test_buttons")

if __name__ == "__main__":

    logging.basicConfig(level=logging.INFO)

    gs = GlobalState()

    dio_stop_event = Event()
    dio_thread = DIOThread(dio_stop_event, gs)
    dio_thread.start()

    last_bits = gs.calibration_diobits
    logger.info("Press and release buttons, ctrl-C to exit")
    logger.info(f"new bits {gs.calibration_diobits:0x}")
    try:
        while True:
            if gs.calibration_diobits != last_bits:
                gstate = " UP "
                rstate = " UP "
                if gs.calibration_diobits&0x1:
                    gstate = "DOWN"
                if gs.calibration_diobits&0x2:
                    rstate = "DOWN"
                logger.info(f"GREEN - {gstate}   RED - {rstate}")
                last_bits = gs.calibration_diobits
            time.sleep(0.1)
    except KeyboardInterrupt:
        dio_stop_event.set()

    dio_thread.join()





    dio_stop_event.set()
    dio_thread.join()

