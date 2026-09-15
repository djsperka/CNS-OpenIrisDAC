import os
import wmi
import xmltodict
import pprint


class EyeTrackerSettings:
    def __init__(self, tracker_folder: str = ''):
        # if tracker folder is not specified, look for exe to find it
        if tracker_folder:
            self.tracker_folder = tracker_folder
        else:
            c = wmi.WMI()
            for process in c.Win32_Process(Name="OpenIris.exe"):
                if process.ExecutablePath:
                    self.tracker_folder = os.path.dirname(process.ExecutablePath)
                    break
            if not self.tracker_folder:
                raise RuntimeError("A running OpenIris executable was not found.")

        # locate settings xml file, but don't open yet
        self.settings_file = os.path.join(self.tracker_folder, "EyeTrackerSettings.xml")

        # make sure settings file exists
        if not os.path.isfile(self.settings_file):
            raise RuntimeError(f"Eye tracker settings file not found at {self.settings_file}")
        
    def get_frame_rate(self, system_type: str = 'Spinnaker Single Camera'):
        i_rate = 0
        found_type = False
        with open(self.settings_file, "rb") as fp:
            d=xmltodict.parse(fp)
            d2 = d['EyeTrackerSettings']['AllEyeTrackerSystemSettings']['item']
            for d3 in d2:
                if d3['key']['string'] == system_type:
                    s_rate = d3['value']['EyeTrackingSystemSettings']['FrameRate']
                    i_rate = int(s_rate)
                    found_type = True
                    break
            if not found_type:
                raise RuntimeError(f"Cannot find system type {system_type} in {self.settings_file}")
        return i_rate
    