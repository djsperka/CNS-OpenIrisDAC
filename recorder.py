"""Binary recording of raw per-frame eye data (left and right) plus Extra ints/doubles.

Each recording produces two files in a folder:
    <prefix>-yyyy-mm-dd-HHMMss.dat   binary frame data (format below)
    <prefix>-yyyy-mm-dd-HHMMss.toml  copy of the config in effect when recording started

File format (little-endian, no padding):

Header (HEADER_SIZE = 64 bytes)
    char[8]   magic  b'OIDACREC'
    uint16    version (1)
    uint16    header_size
    uint32    record_size
    float64   start time (unix epoch seconds)
    uint32    capture_fps
    char[8]   calibration eye (ascii, NUL padded)
    padding to 64 bytes

Record (RECORD_SIZE = 190 bytes), repeated once per frame
    left eye, then right eye, each 41 bytes:
        int64   frame_number
        float32 pupil_x, pupil_y
        float64 pupil_area
        float32 cr_x, cr_y, p4_x, p4_y
        uint8   err_flags  (bit0 = cr_error, bit1 = p4_error, bit2 = 'No Data')
    int32[9]    extra ints
    float64[9]  extra doubles

Use read_recording() to load a file as a numpy structured array.
"""
from pathlib import Path
import struct
import threading
import time
import logging

import numpy as np
import tomlkit

from open_iris_client import EyesData, EyeData

logger = logging.getLogger("DataRecorder")

MAGIC = b'OIDACREC'
VERSION = 1
HEADER_SIZE = 64
_HEADER = struct.Struct('<8sHHIdI8s')

_EYE_FMT = 'qffdffffB'
_RECORD = struct.Struct('<' + _EYE_FMT + _EYE_FMT + '9i' + '9d')
RECORD_SIZE = _RECORD.size

ERR_CR = 0x01
ERR_P4 = 0x02
ERR_NO_DATA = 0x04

_EYE_DTYPE = [('frame_number', '<i8'),
              ('pupil_x', '<f4'), ('pupil_y', '<f4'),
              ('pupil_area', '<f8'),
              ('cr_x', '<f4'), ('cr_y', '<f4'),
              ('p4_x', '<f4'), ('p4_y', '<f4'),
              ('err_flags', 'u1')]
RECORD_DTYPE = np.dtype([('left', _EYE_DTYPE),
                         ('right', _EYE_DTYPE),
                         ('ints', '<i4', (9,)),
                         ('doubles', '<f8', (9,))])
assert RECORD_DTYPE.itemsize == RECORD_SIZE


def _eye_fields(eye: EyeData):
    flags = 0
    if eye.cr_error:
        flags |= ERR_CR
    if eye.p4_error:
        flags |= ERR_P4
    if eye.cr_error == 'No Data':
        flags |= ERR_NO_DATA
    return (int(eye.frame_number),
            float(eye.pupil.x), float(eye.pupil.y),
            float(eye.pupil_area),
            float(eye.cr.x), float(eye.cr.y),
            float(eye.p4.x), float(eye.p4.y),
            flags)


class DataRecorder:
    """Thread-safe writer of EyesData frames to a binary file.

    start()/stop() may be called from any thread (GUI, calibrator comm); write() is
    called from the DataPipeline thread for every frame.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._fp = None
        self._path: Path | None = None
        self._frames_written = 0

    @property
    def recording(self) -> bool:
        return self._fp is not None

    @property
    def current_path(self) -> Path | None:
        return self._path

    @property
    def frames_written(self) -> int:
        return self._frames_written

    def start(self, folder: Path, prefix: str, config_doc, capture_fps: int = 0, eye: str = '') -> Path:
        """Open a new recording. Raises RuntimeError if already recording, OSError on file problems."""
        prefix = prefix.strip()
        if not prefix:
            raise ValueError("Recording prefix must not be empty")
        folder = Path(folder)
        if not folder.is_dir():
            raise FileNotFoundError(f"Recording folder does not exist: {folder}")
        with self._lock:
            if self._fp is not None:
                raise RuntimeError(f"Already recording to {self._path}")
            start_time = time.time()
            basename = f"{prefix}-{time.strftime('%Y-%m-%d-%H%M%S', time.localtime(start_time))}"
            dat_path = folder / f"{basename}.dat"
            toml_path = folder / f"{basename}.toml"
            fp = open(dat_path, 'xb', buffering=1 << 16)
            try:
                header = _HEADER.pack(MAGIC, VERSION, HEADER_SIZE, RECORD_SIZE, start_time,
                                      int(capture_fps), eye.encode('ascii', 'replace')[:8])
                fp.write(header.ljust(HEADER_SIZE, b'\0'))
                with open(toml_path, 'x') as tf:
                    tf.write(tomlkit.dumps(config_doc))
            except Exception:
                fp.close()
                raise
            self._fp = fp
            self._path = dat_path
            self._frames_written = 0
        logger.info(f"Recording started: {dat_path}")
        return dat_path

    def stop(self):
        """Close the current recording, if any."""
        with self._lock:
            if self._fp is None:
                return
            self._fp.close()
            self._fp = None
            logger.info(f"Recording stopped: {self._path} ({self._frames_written} frames)")

    def write(self, data: EyesData):
        if self._fp is None:    # cheap check without lock
            return
        rec = _RECORD.pack(*_eye_fields(data.left), *_eye_fields(data.right),
                           *(int(i) for i in data.extra.ints), *(float(d) for d in data.extra.doubles))
        with self._lock:
            if self._fp is None:
                return
            self._fp.write(rec)
            self._frames_written += 1


def read_recording(path) -> tuple[dict, np.ndarray]:
    """Read a .dat recording. Returns (header dict, structured array with RECORD_DTYPE)."""
    with open(path, 'rb') as fp:
        raw = fp.read(HEADER_SIZE)
        magic, version, header_size, record_size, start_time, fps, eye = _HEADER.unpack_from(raw)
        if magic != MAGIC:
            raise ValueError(f"{path}: not a recording file (bad magic {magic!r})")
        if record_size != RECORD_SIZE:
            raise ValueError(f"{path}: record size {record_size} does not match expected {RECORD_SIZE}")
        fp.seek(header_size)
        body = fp.read()
    n = len(body) // record_size    # ignore a trailing partial record
    records = np.frombuffer(body[:n * record_size], dtype=RECORD_DTYPE)
    header = {'version': version, 'header_size': header_size, 'record_size': record_size,
              'start_time': start_time, 'capture_fps': fps, 'eye': eye.rstrip(b'\0').decode('ascii')}
    return header, records


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Summarize a .dat recording")
    parser.add_argument("path")
    args = parser.parse_args()
    hdr, recs = read_recording(args.path)
    print(hdr)
    print(f"{len(recs)} records")
    if len(recs):
        print("first:", recs[0])
        print("last: ", recs[-1])
