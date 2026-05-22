from threading import Lock

# use this lock for the AIOUSB backend
ao_lock = Lock()

# use this lock for the calibration parameters
cal_lock = Lock()
