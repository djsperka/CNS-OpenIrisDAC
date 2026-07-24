from diothread import DIOThread
from threading import Thread, Event
from open_iris_client import OpenIrisClient, Point, EyesData, EyeData, ExtraData
from calibrator_comm import CalibratorComm
from calibrator_analyzer import Calibrator
import PySimpleGUI as sg
import time
from platformdirs import PlatformDirs as PlatformDirs
from pathlib import Path
from dataclasses import dataclass
import math
import argparse
import datetime
import pickle
from dac_common import AnalogOutput, AnalogOutputPair
from globalstate import GlobalState
from generator import FakeEyeDataGenerator, OpenIrisClientGenerator
import logging
from typing import Callable
import matplotlib.pyplot as plt

logger = logging.getLogger(__name__)

class GUIField:
    def __init__(self, title:str, key:str, size:tuple, obj:object, field:str, gain_factor:float=1, increment:float=1, multiplicative:bool=False,
                slider_enabled:bool=False, slider_minimum:float=-100, slider_maximum:float=100, slider_resolution:float=1, 
                flip_enabled:bool=False):
        self.title = title
        self.key = key
        self.size = size
        self.object = obj
        self.field = field
        self.default_value = getattr(obj, field) / gain_factor
        self.setter = lambda x: setattr(obj, field, x)
        self.getter = lambda : getattr(obj, field)
        self.gain_factor = gain_factor
        self.increment = increment
        self.multiplicative = multiplicative
        self.slider_enabled = slider_enabled
        self.slider_minimum = slider_minimum
        self.slider_maximum = slider_maximum
        self.slider_resolution = slider_resolution
        self.flip_enabled = flip_enabled
        if self.flip_enabled:
            self.flip_default = self.default_value < 0
            self.default_value = abs(self.default_value)

    def get_layout(self):
        layout_left = []
        layout_right = []
        layout_left.append([sg.Text(self.title, size=10)])
        if self.flip_enabled:
            layout_left.append([sg.Checkbox('Flip', key=self.key+'_flip', default=self.flip_default, enable_events=True)])
        layout_right.append([
                        sg.Button('<', key=self.key+'_dec', enable_events=True, s=(1, self.size[1])), 
                        sg.InputText(default_text=self.default_value, s=(self.size[0], self.size[1]), key=self.key+'_input', enable_events=True),
                        sg.Button('>', key=self.key+'_inc', enable_events=True, s=(1, self.size[1]))
                    ])
        if self.slider_enabled:
            layout_right.append([sg.Slider((self.slider_minimum, self.slider_maximum), orientation='h', s=(self.size[0]+3, 15), disable_number_display=True,
                        default_value=self.default_value, resolution=self.slider_resolution, key=self.key+'_slider', enable_events=True)])
        layout = []
        layout.append([sg.Column(layout_left, element_justification='left'), sg.Column(layout_right, element_justification='right')])
        layout.append([sg.HSeparator()])
        return sg.Column(layout)
    
    def sync_state(self, window):
        state = self.getter()
        if self.flip_enabled:
            sign = state < 0
            window[self.key+'_flip'].update(value=sign)
            state = abs(state)
        
        old_input = window[self.key+'_input'].get()
        new_input = str(state/self.gain_factor)
        if old_input != new_input:
            window[self.key+'_input'].update(value=f'{state/self.gain_factor:g}')
        if self.slider_enabled:
            old_slider = window[self.key+'_slider'].widget.get()
            new_slider = state/self.gain_factor
            if old_slider != new_slider:
                window[self.key+'_slider'].update(value=state/self.gain_factor)
        
    def update(self, window, event:str, values:dict):
        if self.key in event:
            flip = (1 - values[self.key+'_flip'] * 2) if self.flip_enabled else 1
            if event == self.key+'_input':
                try:
                    self.setter(float(values[event]) * self.gain_factor * flip)
                except:
                    pass
            if event == self.key+'_inc':
                if self.multiplicative:
                    self.setter(self.getter() * (1+self.increment))
                else:
                    self.setter(self.getter() + self.increment * self.gain_factor * flip)
            if event == self.key+'_dec':
                if self.multiplicative:
                    self.setter(self.getter() * (1-self.increment))
                else:
                    self.setter(self.getter() - self.increment * self.gain_factor * flip)
            if event == self.key+'_slider':
                self.setter(values[event] * self.gain_factor * flip)
            if event == self.key+'_flip':
                self.setter(self.getter() * -1)
            self.sync_state(window)

class GUI:
    colorlist = ['#e6194b', '#3cb44b', '#ffe119', '#4363d8', '#f58231', '#911eb4', '#46f0f0', '#f032e6', '#bcf60c', '#fabebe', '#008080', '#e6beff', '#9a6324', '#fffac8', '#800000', '#aaffc3', '#808000', '#ffd8b1', '#000075']
    def __init__(self, state:GlobalState) -> None:
        self.state = state

        menu_def = [['File', ['Save Config', 'Load Config', 'Exit']]]

        def make_column(title, key, size, resolution, default_value, minimum, maximum, append=[]):
            return sg.Column([
                [sg.Text(title)], 
                [sg.Slider((minimum,maximum), default_value=default_value, s=size, resolution=resolution, k=key, enable_events=True)],
                append
                ])
        
        field_size = (10,1)

        # DJS - changing gain, bias factor to 1
        self.bias_factor = 1

        self.gain_factor = 1
        b_min = -100
        b_max = 100
        b_res = .2
        g_min = 0
        g_max = 10
        g_res = .1



        # move pupil tab first
        self.pupil_bias_factor = 3e3
        self.pupil_gain_factor = 3e-7
        self.plb = GUIField(
            'LPupil Bias', 'left_pupil_bias', field_size, 
            self.state.pupil_cal, 'x_bias', gain_factor=self.pupil_bias_factor, 
            increment=1, multiplicative=False
            )
        self.prb = GUIField(
            'Right Pupil Bias', 'right_pupil_bias', field_size, 
            self.state.pupil_cal, 'y_bias', gain_factor=self.pupil_bias_factor,
            increment=1, multiplicative=False
            )
        self.plg = GUIField(
            'LPupil Gain', 'left_pupil_gain', field_size, 
            self.state.pupil_cal, 'x_gain', gain_factor=self.pupil_gain_factor, 
            increment=0.05, multiplicative=True, flip_enabled=True,
            slider_enabled=True, slider_minimum=g_min, slider_maximum=g_max, slider_resolution=g_res
            )
        self.prg = GUIField(
            'Right Pupil Gain', 'right_pupil_gain', field_size, 
            self.state.pupil_cal, 'y_gain', gain_factor=self.pupil_gain_factor,
            increment=0.05, multiplicative=True, flip_enabled=True,
            slider_enabled=True, slider_minimum=g_min, slider_maximum=g_max, slider_resolution=g_res
            )
        self.lbx = GUIField(
            'X Bias', 'left_x_bias', field_size,
            self.state.left_cal, 'x_bias', gain_factor=self.bias_factor,
            increment=.5, multiplicative=False,
            slider_enabled=True, slider_minimum=b_min, slider_maximum=b_max, slider_resolution=b_res
            )
        self.lby = GUIField(
            'Y Bias', 'left_y_bias', field_size,
            self.state.left_cal, 'y_bias', gain_factor=self.bias_factor,
            increment=.5, multiplicative=False,
            slider_enabled=True, slider_minimum=b_min, slider_maximum=b_max, slider_resolution=b_res
            )
        self.lgx = GUIField(
            'X Gain', 'left_x_gain', field_size,
            self.state.left_cal, 'x_gain', gain_factor=self.gain_factor,
            increment=0.05, multiplicative=True, flip_enabled=True,
            slider_enabled=True, slider_minimum=g_min, slider_maximum=g_max, slider_resolution=g_res
            )
        self.lgy = GUIField(
            'Y Gain', 'left_y_gain', field_size,
            self.state.left_cal, 'y_gain', gain_factor=self.gain_factor,
            increment=0.05, multiplicative=True, flip_enabled=True,
            slider_enabled=True, slider_minimum=g_min, slider_maximum=g_max, slider_resolution=g_res
            )
        self.lr = GUIField(
            'Rotation', 'left_rotation', field_size,
            self.state.left_cal, 'rotation', gain_factor=1,
            increment=1, multiplicative=False,
            slider_enabled=True, slider_minimum=-180, slider_maximum=180, slider_resolution=1
            )
        
        method_layout = []
        method_layout.append(sg.Column([[sg.Text('Method: ')]]))
        method_layout.append(
            sg.Column(
                [
                    [ sg.Radio('DPI (P1-P4)', 'left_method', key='left_dpi', default=self.state.left_method=='dpi', enable_events=True) ],
                    [ sg.Radio('PCR (P1-Pupil)', 'left_method', key='left_pcr', default=self.state.left_method=='pcr', enable_events=True) ]
                ]
            ))

        self.graph = sg.Graph(canvas_size=(600,600), graph_bottom_left=(-5.1,-5.1), graph_top_right=(5.1,5.1), background_color='white', key='graph')

        graph_col = sg.Column([
            [sg.Text('', key='error', size=(20,1), text_color='red')],
            [self.graph]
            ])

        dd_col = sg.Column([
            [self.lbx.get_layout()],
            [self.lby.get_layout()],
            [self.lgx.get_layout()],
            [self.lgy.get_layout()],
            [self.lr.get_layout()],
            [self.plb.get_layout()],
            [self.plg.get_layout()],
            [sg.VPush()],
            [sg.Button(' Zero ', key='left_zero', enable_events=True, button_color='DodgerBlue')],
            method_layout
            ])

        lt = sg.Tab('Left Eye', [[dd_col,graph_col]])
        
        self.rbx = GUIField(
            'X Bias', 'right_x_bias', field_size,
            self.state.right_cal, 'x_bias', gain_factor=self.bias_factor,
            increment=1, multiplicative=False,
            slider_enabled=True, slider_minimum=b_min, slider_maximum=b_max, slider_resolution=b_res
            )
        self.rby = GUIField(
            'Y Bias', 'right_y_bias', field_size,
            self.state.right_cal, 'y_bias', gain_factor=self.bias_factor,
            increment=1, multiplicative=False,
            slider_enabled=True, slider_minimum=b_min, slider_maximum=b_max, slider_resolution=b_res
            )
        self.rgx = GUIField(
            'X Gain', 'right_x_gain', field_size,
            self.state.right_cal, 'x_gain', gain_factor=self.gain_factor,
            increment=0.05, multiplicative=True, flip_enabled=True,
            slider_enabled=True, slider_minimum=g_min, slider_maximum=g_max, slider_resolution=g_res
            )
        self.rgy = GUIField(
            'Y Gain', 'right_y_gain', field_size,
            self.state.right_cal, 'y_gain', gain_factor=self.gain_factor,
            increment=0.05, multiplicative=True, flip_enabled=True,
            slider_enabled=True, slider_minimum=g_min, slider_maximum=g_max, slider_resolution=g_res
            )
        self.rr = GUIField(
            'Rotation', 'right_rotation', field_size,
            self.state.right_cal, 'rotation', gain_factor=1,
            increment=1, multiplicative=False,
            slider_enabled=True, slider_minimum=-180, slider_maximum=180, slider_resolution=1
            )
        rt = sg.Tab('Right Eye', [
            [self.rbx.get_layout()],
            [self.rby.get_layout()],
            [self.rgx.get_layout()],
            [self.rgy.get_layout()],
            [self.rr.get_layout()],
            [sg.VPush()],
            [sg.Text('Method: '),
                sg.Radio('DPI (P1-P4)', 'right_method', key='right_dpi', default=self.state.right_method=='dpi', enable_events=True), 
                sg.Radio('PCR (P1-Pupil)', 'right_method', key='right_pcr', default=self.state.right_method=='pcr', enable_events=True)
            ]])
        
        self.output_list = list(self.state.output_dict.keys())
        self.output_list.insert(0, 'None')
        settings_layout = [
            [sg.Text('Channels: ')],
            [sg.Text('Eye X: '), sg.Combo(self.output_list, default_value=self.output_list[1] if len(self.output_list) > 1 else 'None', 
                                           key='left_x_channel', enable_events=True)],
            [sg.Text('Eye Y: '), sg.Combo(self.output_list, default_value=self.output_list[2] if len(self.output_list) > 2 else 'None', 
                                            key='left_y_channel', enable_events=True)],
            [sg.Text('Pupil: '), sg.Combo(self.output_list, default_value=self.output_list[5] if len(self.output_list) > 5 else 'None', 
                                            key='pupil_x_channel', enable_events=True)]
        ]
        st = sg.Tab('Settings', settings_layout)

        # tab for calibration plots

        self.raw_graph = sg.Graph(canvas_size=(400,400), graph_bottom_left=(-105,-105), graph_top_right=(105,105), background_color='white', key='graph')
        self.cal_graph = sg.Graph(canvas_size=(400,400), graph_bottom_left=(-5.1,-5.1), graph_top_right=(5.1,5.1), background_color='white', key='graph')
        graph_column = sg.Column([[self.raw_graph],[self.cal_graph]], element_justification='center')

        # second column for other stuff. Initially, a button to test calibration.
        other_column = sg.Column([[sg.Button('Fake cal', key='start-fake-cal', enable_events=True, button_color='PaleVioletRed4')],
                                  [sg.Button('Stop cal', key='stop-fake-cal', enable_events=True, button_color='PaleVioletRed4')],
                                  [sg.Button('Fit', key='do-cal-fit', enable_events=True, button_color='PaleVioletRed4')],
                                  [sg.Button('Accept', key='cal-accept', enable_events=True, button_color='PaleVioletRed4')],
                                  [sg.Button('Clear', key='cal-clear', enable_events=True, button_color='PaleVioletRed4')],
                                  [sg.Button('Load', key='cal-load', enable_events=True, button_color='PaleVioletRed4')]])
        calibration_layout = [[graph_column,other_column]]        
        ct = sg.Tab('Calibration', calibration_layout)

        tabs = sg.TabGroup([[lt,ct,st]], key='tabs', expand_y=True)
        
        self.layout = [
            [sg.Menu(menu_def)],
            [tabs]
        ]

    def update_sliders(self):
        self.lbx.sync_state(self.window)
        self.lby.sync_state(self.window)
        self.lgx.sync_state(self.window)
        self.lgy.sync_state(self.window)
        self.lr.sync_state(self.window)
        self.rbx.sync_state(self.window)
        self.rby.sync_state(self.window)
        self.rgx.sync_state(self.window)
        self.rgy.sync_state(self.window)
        self.rr.sync_state(self.window)
        self.plb.sync_state(self.window)
        self.prb.sync_state(self.window)
        self.plg.sync_state(self.window)
        self.prg.sync_state(self.window)

    def update_output_channels(self):
        left_x = self.state.output_dict[self.window['left_x_channel'].get()] if self.window['left_x_channel'].get() != 'None' else AnalogOutput()
        left_y = self.state.output_dict[self.window['left_y_channel'].get()] if self.window['left_y_channel'].get() != 'None' else AnalogOutput()
        left_pupil = self.state.output_dict[self.window['pupil_x_channel'].get()] if self.window['pupil_x_channel'].get() != 'None' else AnalogOutput()
        # right_x = self.state.output_dict[self.window['right_x_channel'].get()] if self.window['right_x_channel'].get() != 'None' else AnalogOutput()
        # right_y = self.state.output_dict[self.window['right_y_channel'].get()] if self.window['right_y_channel'].get() != 'None' else AnalogOutput()
        # right_pupil = self.state.output_dict[self.window['pupil_y_channel'].get()] if self.window['pupil_y_channel'].get() != 'None' else AnalogOutput()
        right_pupil = AnalogOutput()
        self.state.left_output = AnalogOutputPair(left_x, left_y)
        # self.state.right_output = AnalogOutputPair(right_x, right_y)
        self.state.pupil_output = AnalogOutputPair(left_pupil, right_pupil)
        
    def update_graph(self):
        self.graph.erase()
        # draw axes
        self.graph.draw_line((-5,0), (5,0))
        self.graph.draw_line((0,-5), (0,5))
        self.graph.draw_line((-5,-5), (-5,5))
        self.graph.draw_line((-5,5), (5,5))
        self.graph.draw_line((5,5),(5,-5))
        self.graph.draw_line((5,-5),(-5,-5))
        self.graph.draw_text('5V', (0.3,4.7), color='black')
        self.graph.draw_text('5V', (4.7,0.3), color='black')
        self.graph.draw_text('-5V', (-0.4,-4.7), color='black')
        self.graph.draw_text('-5V', (-4.6,-0.3), color='black')
        
        for xy in range(-5, 6):
            self.graph.draw_line((xy,-0.1), (xy,0.1))
            self.graph.draw_line((-0.1,xy), (0.1,xy))
        
        clip = lambda x: min(max(x, -5), 5)
        rx = clip(self.state.right_output.v_out.x)
        ry = clip(self.state.right_output.v_out.y)
        lx = clip(self.state.left_output.v_out.x) 
        ly = clip(self.state.left_output.v_out.y)
        px = clip(self.state.pupil_output.v_out.x) 
        py = clip(self.state.pupil_output.v_out.y)
        self.graph.draw_point((rx, ry), size=.15, color='firebrick1')
        self.graph.draw_point((lx, ly), size=.15, color='DodgerBlue')
        self.graph.draw_point((px, py), size=.15, color='DarkGoldenrod1')
        
        int0 = self.state.last_eyes_data.extra.ints[0] & 1
        int1 = self.state.last_eyes_data.extra.ints[1] & 1
        self.graph.draw_point((4.3, -4.7), size=.30, color='green' if int0 else 'red')
        self.graph.draw_point((4.7, -4.7), size=.30, color='green' if int1 else 'red')

    def update_calibration_graphs(self):
        self.raw_graph.erase()
        self.raw_graph.draw_line((-100,-100), (-100,100))
        self.raw_graph.draw_line((-100,100),(100,100))
        self.raw_graph.draw_line((100,100), (100,-100))
        self.raw_graph.draw_line((100,-100), (-100,-100))


        self.cal_graph.erase()
        self.cal_graph.draw_line((-5,0), (5,0))
        self.cal_graph.draw_line((0,-5), (0,5))
        self.cal_graph.draw_line((-5,-5), (-5,5))
        self.cal_graph.draw_line((-5,5), (5,5))
        self.cal_graph.draw_line((5,5),(5,-5))
        self.cal_graph.draw_line((5,-5),(-5,-5))
        self.cal_graph.draw_text('5V', (0.3,4.7), color='black')
        self.cal_graph.draw_text('5V', (4.7,0.3), color='black')
        self.cal_graph.draw_text('-5V', (-0.4,-4.7), color='black')
        self.cal_graph.draw_text('-5V', (-4.6,-0.3), color='black')
        for xy in range(-5, 6):
            self.cal_graph.draw_line((xy,-0.1), (xy,0.1))
            self.cal_graph.draw_line((-0.1,xy), (0.1,xy))

        m = self.state.calibrator.measurements
        b, tempCal = self.state.calibrator.get_cal()
        for i, (key,pts) in enumerate(m.items()):
            for p in pts:
                # draw raw point
                self.raw_graph.draw_point((p[0], p[1]), color=self.colorlist[i], size=4)

                # If a valid calibration exists (one that we created here, not the "official" one in state.
                if b:
                    pp = tempCal.transform(Point(p[0], p[1]))
                    self.cal_graph.draw_point((pp.x, pp.y), color=self.colorlist[i], size=0.2)

    def window_loop(self, verbose=False):
        
        self.window = sg.Window('OpenIrisClient', self.layout)
        self.window.timer_start(500, key='calibration-graphs', repeating=True)
        first = True
        while self.state.is_running:
            event, values = self.window.read(timeout=20) # 20ms = 50Hz
            # if event != '__TIMEOUT__':
            #     print(event, values)
            if first:
                self.update_output_channels()
                first = False
            if verbose and event != sg.TIMEOUT_EVENT:
                logger.info(event, values)

            # handle exit
            if event == sg.WIN_CLOSED or event == 'Close' or event == 'Exit':
                self.state.is_running = False
                break
            
            # Update left method
            if event in ['left_dpi', 'left_pcr']:
                if values['left_dpi']:
                    self.state.left_method = 'dpi'
                elif values['left_pcr']:
                    self.state.left_method = 'pcr'
                else:
                    self.state.left_method = 'dpi'
            
            # Update right method
            if event in ['right_dpi', 'right_pcr']:
                if values['right_dpi']:
                    self.state.right_method = 'dpi'
                elif values['right_pcr']:
                    self.state.right_method = 'pcr'
                else:
                    self.state.right_method = 'dpi'

            # Update states
            self.rbx.update(self.window, event, values)
            self.rby.update(self.window, event, values)
            self.rgx.update(self.window, event, values)
            self.rgy.update(self.window, event, values)
            self.rr.update(self.window, event, values)
            self.lbx.update(self.window, event, values)
            self.lby.update(self.window, event, values)
            self.lgx.update(self.window, event, values)
            self.lgy.update(self.window, event, values)
            self.lr.update(self.window, event, values)
            self.plb.update(self.window, event, values)
            self.prb.update(self.window, event, values)
            self.plg.update(self.window, event, values)
            self.prg.update(self.window, event, values)

            # Update output channels
            if event in ['left_x_channel', 'left_y_channel', 'right_x_channel', 'right_y_channel', 'pupil_x_channel', 'pupil_y_channel']:
                self.update_output_channels()

            # Zero left
            if event == 'left_zero':
                last_left = self.state.last_eyes_data.left.cr - \
                    (self.state.last_eyes_data.left.pupil if self.state.left_method == 'pcr' else self.state.last_eyes_data.left.p4)
                print(last_left)
                self.state.left_cal.x_bias = -last_left.x
                self.state.left_cal.y_bias = -last_left.y
                print(self.state.left_cal.x_bias, self.state.left_cal.y_bias)
                print(self.state.left_cal.transform(last_left))
                self.lbx.sync_state(self.window)
                self.lby.sync_state(self.window)
            
            
            # Zero right
            if event == 'right_zero':
                last_right = self.state.last_eyes_data.right.cr - \
                    (self.state.last_eyes_data.right.pupil if self.state.right_method == 'pcr' else self.state.last_eyes_data.right.p4)
                self.state.right_cal.x_bias = -last_right.x
                self.state.right_cal.y_bias = -last_right.y
                self.rbx.sync_state(self.window)
                self.rby.sync_state(self.window)

            # Switch left and right
            if event == 'switch':
                temp = self.state.left_output
                self.state.left_output = self.state.right_output
                self.state.right_output = temp

                temp = self.window['right_x_channel'].get()
                self.window['right_x_channel'].update(value=self.window['left_x_channel'].get())
                self.window['left_x_channel'].update(value=temp)

                temp = self.window['right_y_channel'].get()
                self.window['right_y_channel'].update(value=self.window['left_y_channel'].get())
                self.window['left_y_channel'].update(value=temp)

            # Save config
            if event == 'Save Config':
                # Open a dialog to select a new file
                save_dir = sg.popup_get_folder('Select save directory', default_path=self.state.save_dir)
                self.state.save(Path(save_dir))

            # Load config
            if event == 'Load Config':
                # Open a folder picking dialog
                load_dir = sg.popup_get_folder('Select directory to load', default_path=self.state.save_dir)
                if load_dir:
                    self.state.load(Path(load_dir))
                    self.update_sliders()

            # for testing only!
            if event == 'start-fake-cal':
                self.state.calibrating = True

            if event == 'stop-fake-cal':
                logger.info("stop-fake-cal")
                self.state.calibrating = False

            if event == 'do-cal-fit':
                logger.info("do-cal-fit")
                self.state.calibrator.dofit()

            if event == 'cal-clear':
                logger.info("cal-clear")
                self.state.calibrator.clear_cal()

            if event == 'cal-accept':
                logger.info('cal-accept')
                b, cal = self.state.calibrator.get_cal()
                if b:
                    self.state.left_cal = cal
                else:
                    logger.error(f"Calibrator does not have a valid calibration.")

            if event == 'cal-load':
                print(f"data path {str(self.state.data_path)}")
                file_to_load = sg.popup_get_file('Select a cal-pkl file to load', initial_folder=str(self.state.data_path), file_types=(('pkl files', '.pkl'),), no_window=True)
                # Build a list of tuples for each file type the file dialog should display
                print(f'File selected: {file_to_load}')

            # update calibration graphs
            if event == 'calibration-graphs':
                if self.state.calibrator and self.state.calibrator.invalidated:
                    self.update_calibration_graphs()
                    self.state.calibrator.invalidated = False

            # update graph and errors on timeout (refresh)
            if event == sg.TIMEOUT_EVENT:
                self.update_graph()

                # Get eye data
                error = self.state.last_eyes_data.get_error(left_p4=self.state.left_method=='dpi', right_p4=self.state.right_method=='dpi')
                if error:
                    self.window['error'].update(value = error, text_color='red')
                else:
                    self.window['error'].update(value = 'Tracking', text_color='lawn green')
                

    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_value, traceback):
        if self.window:
            self.window.close()
        
        self.state.is_running = False

        if exc_type:
            print(exc_type, exc_value, traceback)
            return False
        return True

    def run(self, verbose=False):
        with self as gui:
            gui.window_loop(verbose)



class DataPipeline:
    def __init__(self, state:GlobalState, fake: bool=False, server_address: str='localhost', port: int=9003, output: str='', fake_file: str='', cal_recording_path=None):
        self.state = state
        self.server_address = server_address
        self.port = port
        self.fake = fake        
        self.output = output
        self.output_file = None
        self.fake_file = fake_file
        self.cal_recording_path = cal_recording_path
        self.cal_recording_fd = None


    def maybe_save_calibration_data(self, data):
        if self.state.calibrating:
            if not self.cal_recording_fd:
                # open file
                fpath = self.cal_recording_path / datetime.datetime.now().strftime("cal-%Y-%m-%d-%H-%M.pkl")
                self.cal_recording_fd = open(fpath, 'wb')
                logger.info(f"Opened file for calibration data: {str(fpath)}")
            pickle.dump(data, self.cal_recording_fd)
        else:
            if self.cal_recording_fd:
                close(self.cal_recording_fd)
                self.cal_recording_fd = None
                logger.info(f"Closed calibration data output file")

    def run(self, debug=False):

        # create generator
        if self.fake:
            generator = FakeEyeDataGenerator(self.state, self.fake_file)
        else:  
            generator = OpenIrisClientGenerator(self.state, self.server_address, self.port)

        for data in generator.generate():    
            self.state.last_eyes_data = data

            if self.state.calibrating:
                # Assign values for current calibration stuff. 
                if not self.fake:
                    # assign dio bits to data.extra.ints[8] 
                    data.extra.ints[8] = self.state.calibration_diobits
                    data.extra.doubles[5] = self.state.calibration_vpdx
                    data.extra.doubles[6] = self.state.calibration_vpdy
                    data.extra.doubles[7] = self.state.calibration_fixation_x
                    data.extra.doubles[8] = self.state.calibration_fixation_y
                # put the EyesData into the queue - it will get picked up by the calibration thread
                self.state.calibration_queue.put(data)

                # Save the calibration data unless command line said not to
                self.maybe_save_calibration_data(data)

            # transform current signal and write to appropriate output
            left_output = data.left.cr - (data.left.pupil if self.state.left_method == 'pcr' else data.left.p4)
            left_output = self.state.left_cal.transform(left_output)
            self.state.left_output.write(left_output)
            
            right_output = data.right.cr - (data.right.pupil if self.state.right_method == 'pcr' else data.right.p4)
            right_output = self.state.right_cal.transform(right_output)
            self.state.right_output.write(right_output)

            pupil_output = Point(data.left.pupil_area, data.right.pupil_area)
            pupil_output = self.state.pupil_cal.transform(pupil_output)
            self.state.pupil_output.write(pupil_output)
            if debug:
                print(data)
                print(f'{left_output}, {right_output}, {pupil_output}')

if __name__ == "__main__":
    from threading import Thread

    logging.basicConfig(level=logging.INFO)
    # Source - https://stackoverflow.com/a/75448196
    # Posted by Marco Spurio Cassio, modified by community. See post 'Timeline' for change history
    # Retrieved 2026-07-17, License - CC BY-SA 4.0
    #plt.set_loglevel(level = 'warning')

    # Single input argument (optional) is filename to write output to.
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", help="File to write output to", type=str, default='')
    parser.add_argument("--fake", help="Use fake data generator instead of OpenIrisClient", action='store_true')
    parser.add_argument("--fake-file", help="pkl file to use as fake calibration data")
    parser.add_argument("--address", help="Address of OpenIrisServer", default='localhost')
    parser.add_argument("--port", help="Port of OpenIrisServer", default=9003, type=int)
    parser.add_argument("--cal-port", help="Port of calibrator server", default=0, type=int)
    parser.add_argument("--no-cal-record", help="DO NOT record data (incl button&FRAME) during calibration", action='store_false')
    args = parser.parse_args()
    if not args.no_cal_record:
        cal_recording_path = PlatformDirs("CNS-OpenIrisDAC", appauthor=False).user_data_path
        # make sure it exists
        cal_recording_path.mkdir(exist_ok=True)
    else:
        cal_recording_path = None

    if not args.fake:
        kwargs = {'server_address': args.address, 'port': args.port}
    else:
        logger.warning('Using fake data generator')
        kwargs = {}


    # with GUI() as gui:
    #     gui.window_loop(open_iris_ip='localhost', verbose=False)
    gs = GlobalState()
    gui_thread = Thread(target=GUI(gs).window_loop, args=(False,))
    gui_thread.start()

    # start calibrator server if specified
    calibrator_comm_thread = None
    calibrator_ana_thread = None
    dio_thread = None
    dio_stop_event = None
    if args.cal_port:
        calibrator_comm_thread = CalibratorComm(gs, port=args.cal_port, verbose=True)
        calibrator_comm_thread.start()
        calibrator_ana_thread = Calibrator(gs)
        gs.calibrator = calibrator_ana_thread
        calibrator_ana_thread.start()
        dio_stop_event = Event()
        dio_thread = DIOThread(dio_stop_event, gs)
        dio_thread.start()

    # start data pipeline
    dp_thread = Thread(target=DataPipeline(gs, fake=args.fake, server_address=args.address, port=args.port, cal_recording_path=cal_recording_path, fake_file=args.fake_file).run, args=(False,))
    dp_thread.start()

    dp_thread.join()
    if args.cal_port:
        calibrator_comm_thread.stop()
        calibrator_comm_thread.join()
        calibrator_ana_thread.stop()
        calibrator_ana_thread.join()
    if dio_thread:
        dio_stop_event.set()
        dio_thread.join()
    gui_thread.join()
    gs.save()
    