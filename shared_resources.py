from threading import Lock

# use this lock for the AIOUSB backend
ao_lock = Lock()

# use this lock for the calibration parameters
cal_lock = Lock()

# use this lock for the in-calibration settings (e.g. calibration_fixation_x, calibration_fixation_y, calibration_vpdx, calibration_vpdy)
in_cal_lock = Lock()
