# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

CNS-OpenIrisDAC is a fork of [OpenIrisDAC](https://github.com/ryan-ressmeyer/OpenIrisDAC), adapted for the Usrey Lab (UC Davis Center for Neuroscience). It is an analog-output client for the [OpenIrisDPI](https://github.com/ryan-ressmeyer/OpenIrisDPI) dual Purkinje-image eye tracker: it receives streaming gaze/pupil data from the OpenIrisDPI control program over UDP, applies a per-eye calibration transform, and writes the result as analog voltages on a DAC so a separate data-acquisition system (e.g. Spike2) can record eye position during an experiment.

The GUI application (`gui.py`) only runs on Windows because it depends on vendor DAC drivers (AIOUSB) and/or NI-DAQmx. Development/testing of the non-hardware logic can be done on any platform using the fake backends described below.

There is no build system, linter config, or test suite in this repo (no `requirements.txt`, `pyproject.toml`, or pytest setup). `test_buttons.py` and `check_frame.py` are manual scratch scripts run directly with `python`, not an automated test suite.

## Running the app

```shell
python gui.py --fake                 # run with simulated eye data (no OpenIrisDPI/hardware needed)
python gui.py --address <ip> --port 9003 --cal-port 9292 --subject <name>
```

Key `gui.py` CLI args: `--fake` (use `FakeOpenIrisClientGenerator` instead of a live OpenIrisDPI UDP connection), `--address`/`--port` (OpenIrisDPI server), `--cal-port` (TCP port for the external calibrator protocol, see below), `--fps`/`--eye` (override auto-detected capture rate / calibration eye), `--tracker-folder` (location of `EyeTrackerSettings.xml`, otherwise auto-discovered via a running `OpenIris.exe` process), `--subject` (selects the config file).

To develop without real DAC hardware, set `DAC_BACKEND=nodac` (default is `dac`). This swaps in `nodac.py`'s `FakeModule`/`discover_ao_modules`/`DIO_Read8` in place of `dac.py`'s AIOUSB/NI-DAQmx code, in both `globalstate.py` and `diothread.py`.

Standalone utility entry points (each has its own `if __name__ == "__main__":`):
- `globalstate.py --subject X --basename Y` — create/load/save a subject's config file.
- `dac.py` / `nodac.py` — list discovered analog-output modules.
- `calibrator_comm.py` — run just the TCP calibrator server.
- `open_iris_client.py` — print raw UDP frames from a running OpenIrisDPI server.

## Architecture

**`GlobalState` (`globalstate.py`)** is the single shared mutable state object threaded through the whole app — the GUI, the data pipeline, the calibrator, and the DIO thread all read/write the same instance. It owns:
- Per-eye/pupil `CalibrationParameters` (bias, gain, rotation) and the `AnalogOutputPair`s that hardware voltages are written to.
- Calibration-session state (`calibrating`, `calibration_fixation_x/y`, `calibration_queue`, frame counters, etc.).
- Config persistence: config is a TOML file at `~/.dpidac/<subject>/<basename>.toml` (NOT the `config.toml` checked into the repo root, which is only a sample/reference). `load_config`/`save_config`/`maybe_create_config` manage this file per-subject.
- `discover_analog_modules()` picks the DAC backend based on the `DAC_BACKEND` env var (`dac` = real hardware via `dac.py`, `nodac` = `FakeModule` via `nodac.py`) and builds `output_dict`, a `{"<module>-ch<n>": AnalogOutput}` map used to assign output channels in the GUI/config.

**`DataPipeline.run()` (`data_pipeline.py`)** is the per-frame hot loop: it pulls `EyesData` frames from an `EyeDataGenerator`, tracks frame-count/missed-frame stats, and — if `state.calibrating` — stamps calibration metadata into `data.extra` and pushes the frame onto `state.calibration_queue` for the `Calibrator` thread. It then computes left/right eye position as `cr - (pupil or p4)` (method chosen by `state.left_method`/`right_method`, `'pcr'` vs the default P1-P4 method), applies the relevant `CalibrationParameters.transform()`, and writes the resulting `Point` (in volts) to the appropriate `AnalogOutputPair`. `is_mouse_mode` overrides the real eye position with `state.mouse_mode_xy` for manual testing from the GUI.

**Units gotcha:** internally, calibrated output and `AnalogOutputPair.v_out` are always in **volts**. The GUI's main graph displays **degrees**, converting at display time using `state.calibration_vpdx`/`vpdy` (volts-per-degree, settable live via the `DEGPERVOLT` calibrator command). Any code path that moves a value between "volts on the wire/DAC" and "degrees on screen" needs to apply/invert that conversion explicitly — a past bug here was converting mouse-canvas coordinates to degrees when volts were expected.

**Data model (`open_iris_client.py`)**: `OpenIrisClient` is a UDP client speaking OpenIrisDPI's simple text protocol (`"getdata"` / `"WAITFORDATA"` request, JSON response). `EyesData`/`EyeData`/`ExtraData` parse that JSON into the dataclasses used everywhere else; `Point` is a thin 2-vector wrapper (numpy-backed) with `+`, `-`, `*`, `rotate()`, `clip()`. `CRs[0]` is the primary corneal reflection, `CRs[3]` is P4 (used for DPI tracking); missing CRs are reported via `cr_error`/`p4_error` rather than raising.

**`generator.py`** provides `EyeDataGenerator` implementations that `DataPipeline` consumes: `OpenIrisClientGenerator` (real UDP stream), `FakeOpenIrisClientGenerator`/`FakeEyeDataGenerator` (synthetic data for dev without the tracker — the latter can also replay a pickled fake-calibration recording), and `FileEyeDataGenerator` (replays a pickle of recorded `EyesData` frames, e.g. the files under `usrey-selected/`).

**DAC abstraction (`dac_common.py`, `dac.py`, `nodac.py`)**: `AnalogModule` is the hardware-agnostic base (voltage range, per-channel write); `AnalogOutput`/`AnalogOutputPair` wrap one or two channels with a `.write()`/`.v_out`. `dac.py` implements `AIOModule` (wraps the `AIOUSB.py` ctypes bindings for AccesIO USB-AO boards) and partial NI-DAQmx support, and asserts `os.name == 'nt'`. `nodac.py` implements `FakeModule`, a pure-Python stand-in with the same interface, used when `DAC_BACKEND=nodac`.

**Calibration subsystem**, which runs as two background threads coordinated through `GlobalState`:
- `CalibratorComm` (`calibrator_comm.py`) is a TCP server (default port 8282, or `--cal-port` on the GUI) that an external stimulus-presentation program (`fixstim`, run on the Spike2 DAQ computer, which has no native networking) drives over a serial-to-TCP bridge. Protocol: client sends `HELLO;`, server replies `OK;`, then semicolon-terminated commands: `calstart`/`calstop` (toggle `state.calibrating`), `F x,y,d,c;` (set the current fixation point and mark it on), `X` (mark fixation off), `DEGPERVOLT dx,dy;` (set `state.calibration_vpdx`/`vpdy`).
- `Calibrator` (`calibrator_analyzer.py`) is a state-machine thread (`INITIALIZE → LOAD → CHECK → IDLE/DONE`) that consumes frames from `state.calibration_queue`, matches them against button-press/fixation events (`ButtonPressInfo`), and fits new `CalibrationParameters` (x/y bias, gain, rotation) with `scipy.optimize.curve_fit` via the `TWrapperClass` transform wrapper.
- `DIOThread` (`diothread.py`) polls the DAC's digital I/O byte (`DIO_Read8`) on a timer and writes it to `state.calibration_diobits`, which the calibrator uses to detect button presses from the behavior rig.
- `shared_resources.py` defines three locks used across these threads — `ao_lock` (DAC hardware I/O), `cal_lock` (calibration parameters), `in_cal_lock` (in-calibration session fields like `calibration_fixation_*`, `calibration_frames_in/out`) — take the appropriate lock before mutating the corresponding `GlobalState` fields from a non-GUI thread.

**`gui.py`** (`GUI` class) is the PySimpleGUI desktop app that wires all of the above together: it owns the `GlobalState`, the chosen `EyeDataGenerator`/`DataPipeline`, the `CalibratorComm`/`Calibrator`/`DIOThread` threads, and draws live graphs (raw eye position, calibrated main-graph output in degrees, and calibration-space fit). `GUIField` is a small reusable widget wrapper (text entry + inc/dec buttons + optional slider/flip checkbox) that two-way binds to an arbitrary object attribute (mostly `CalibrationParameters` fields) — used to build the live calibration-tuning controls.

**`eye_tracker_settings.py`** reads OpenIrisDPI's own `EyeTrackerSettings.xml` (locating it via a running `OpenIris.exe` process through `wmi` if `--tracker-folder` isn't given) to auto-detect the capture frame rate and which eye is tracked.

## Repo notes

- Several top-level scripts (`sel.py`, `sel2.py`, `cb.py`, `pl99.py`, `ppl.py`, `tw.py`, `traygui.py`, `configtest.py`) are untracked scratch/experiment files, not part of the shipped app — don't assume they're wired into `gui.py` unless you check.
- `usrey-selected/*.pkl` are recorded `EyesData` sessions for use with `FileEyeDataGenerator`/`FakeEyeDataGenerator`; `cals/` is gitignored and used for local calibration output.
- `.env` is untracked (not currently gitignored) — never read/print its contents into chat, and don't add it to a commit.
