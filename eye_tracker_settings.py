import os
import wmi
import xmltodict
import pprint


class EyeTrackerSettings:
    def __init__(self, tracker_folder: str = ''):
        """This class will get the frame rate from the settings file for the OpenIris eye tracker application. It can be modified to read other settings in that file -- I just need the frames per second.

        Args:
            tracker_folder (string, optional): Folder where the OpenIris.exe executable file lives. If not specified, there must be a process named 'OpenIris.exe' currently running. Defaults to ''.

        Raises:
            RuntimeError: If no folder specified and no running OpenIris.exe was found, or if no settings file 'EyeTrackerSettings.xml' is found there.
        """

        # if tracker folder is not specified, look for exe to find it
        self.tracker_folder = tracker_folder
        if not self.tracker_folder:
            c = wmi.WMI()
            for process in c.Win32_Process(Name="OpenIris.exe"):
                if process.ExecutablePath:
                    self.tracker_folder = os.path.dirname(process.ExecutablePath)
                    break
            if not self.tracker_folder:
                raise RuntimeError("Tracker folder not specified, and a running OpenIris executable was not found.")

        # locate settings xml file, but don't open yet
        self.settings_file = os.path.join(self.tracker_folder, "EyeTrackerSettings.xml")

        # make sure settings file exists
        if not os.path.isfile(self.settings_file):
            raise RuntimeError(f"Eye tracker settings file not found at {self.settings_file}")
        
    def get_frame_rate(self, system_type: str = 'Spinnaker Single Camera'):
        """Get the frame capture rate for the given system type.

        Args:
            system_type (str, optional): One of the system types. A system type corresponds to a key to one of the items under 'AllEyeTrackerSystemSettings' in the settings file. Defaults to 'Spinnaker Single Camera'.

        Raises:
            RuntimeError: If the system type supplied is not found in the settings file.

        Returns:
            integer: Frame capture rate, in frames per second.
        """
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
    