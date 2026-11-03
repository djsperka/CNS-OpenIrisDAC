from diothread import DIOThread
from threading import Thread, Event
from open_iris_client import Point
from calibrator_comm import CalibratorComm
from calibrator_analyzer import Calibrator
from data_pipeline import DataPipeline
from eye_tracker_settings import EyeTrackerSettings
from generator import OpenIrisClientGenerator, FakeEyeDataGenerator
import PySimpleGUI as sg
from platformdirs import PlatformDirs
from pathlib import Path
import copy
import numpy as np
import argparse
import time
from dac_common import AnalogOutput, AnalogOutputPair
from globalstate import GlobalState
import logging
from shared_resources import cal_lock
from dac_common import CalibrationParameters

logger = logging.getLogger(__name__)
MAIN_GRAPH_CANVAS_SIZE = (600, 600)
#MAIN_GRAPH_BOTTOM_LEFT = (-5.1, -5.1)
#MAIN_GRAPH_TOP_RIGHT = (5.1, 5.1)
RAW_GRAPH_CANVAS_SIZE = (400, 400)
RAW_GRAPH_BOTTOM_LEFT = (-105, -105)
RAW_GRAPH_TOP_RIGHT = (105, 105)
CAL_GRAPH_CANVAS_SIZE = (400, 400)
CAL_GRAPH_BOTTOM_LEFT = (-5.1, -5.1)
CAL_GRAPH_TOP_RIGHT = (5.1, 5.1)
MAX_VOLTS = 5.0


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
    def __init__(self, state:GlobalState, calibrator:Calibrator|None) -> None:
        self.state = state
        self.calibrator = calibrator

    def update_sliders(self):
        self.lbx.sync_state(self.window)
        self.lby.sync_state(self.window)
        self.lgx.sync_state(self.window)
        self.lgy.sync_state(self.window)
        self.lr.sync_state(self.window)
        self.plb.sync_state(self.window)
        self.plg.sync_state(self.window)
        for f in self.dpi_fields:
            f.sync_state(self.window)

    def update_output_channels(self):
        """Event callback for any of the analog output channel combo boxes. Only the left eye outputs are configured here! The state variables
        containing the keys are also updated, but are only used when the config is saved. This method will get called twice, as there are two events
        associated with changing a selection. The first will have all current values, the second call will see the changed value.
        """
        self.state.left_x_channel = self.window['left_x_channel'].get()
        self.state.left_y_channel = self.window['left_y_channel'].get()
        self.state.pupil_x_channel = self.window['pupil_x_channel'].get()
        self.state.left_dpi_x_channel = self.window['left_dpi_x_channel'].get()
        self.state.left_dpi_y_channel = self.window['left_dpi_y_channel'].get()
        left_x = self.state.output_dict[self.window['left_x_channel'].get()] if self.window['left_x_channel'].get() != 'None' else AnalogOutput()
        left_y = self.state.output_dict[self.window['left_y_channel'].get()] if self.window['left_y_channel'].get() != 'None' else AnalogOutput()
        left_pupil = self.state.output_dict[self.window['pupil_x_channel'].get()] if self.window['pupil_x_channel'].get() != 'None' else AnalogOutput()
        right_pupil = AnalogOutput()
        left_dpi_x = self.state.output_dict[self.state.left_dpi_x_channel] if self.state.left_dpi_x_channel != 'None' else AnalogOutput()
        left_dpi_y = self.state.output_dict[self.state.left_dpi_y_channel] if self.state.left_dpi_y_channel != 'None' else AnalogOutput()
        self.state.left_output = AnalogOutputPair(left_x, left_y)
        self.state.left_dpi_output = AnalogOutputPair(left_dpi_x, left_dpi_y)
        self.state.pupil_output = AnalogOutputPair(left_pupil, right_pupil)
        
    def update_graph(self):
        # clear graph
        self.graph.erase()

        # TODO - make checkbox to display degrees or volts
        showDegrees = True

        # update coord system. Only needed when vpdx, vpdy change! 
        # These are max (degrees), assuming that the DAC puts out values from -MAX_VOLTS to MAX_VOLTS.
        # Assign current values to be output, depending on whether we're showing degrees or volts.
        if showDegrees:
            graph_x_max = MAX_VOLTS / self.state.calibration_vpdx
            graph_y_max = MAX_VOLTS / self.state.calibration_vpdy
            right_x = self.state.right_output.v_out.x / self.state.calibration_vpdx
            right_y = self.state.right_output.v_out.y / self.state.calibration_vpdy
            left_x = self.state.left_output.v_out.x / self.state.calibration_vpdx
            left_y = self.state.left_output.v_out.y / self.state.calibration_vpdy
            left_dpi_x = self.state.left_dpi_output.v_out.x / self.state.calibration_vpdx
            left_dpi_y = self.state.left_dpi_output.v_out.y / self.state.calibration_vpdy
            pupil_x = self.state.pupil_output.v_out.x / self.state.calibration_vpdx
            pupil_y = self.state.pupil_output.v_out.y / self.state.calibration_vpdy
        else:
            graph_x_max = MAX_VOLTS
            graph_y_max = MAX_VOLTS
            right_x = self.state.right_output.v_out.x
            right_y = self.state.right_output.v_out.y
            left_x = self.state.left_output.v_out.x
            left_y = self.state.left_output.v_out.y
            left_dpi_x = self.state.left_dpi_output.v_out.x
            left_dpi_y = self.state.left_dpi_output.v_out.y
            pupil_x = self.state.pupil_output.v_out.x
            pupil_y = self.state.pupil_output.v_out.y

        self.graph.change_coordinates(graph_bottom_left=(-graph_x_max, -graph_y_max), graph_top_right=(graph_x_max, graph_y_max))

        # draw axes
        self.graph.draw_line((-graph_x_max,0), (graph_x_max,0))
        self.graph.draw_line((0,-graph_y_max), (0,graph_y_max))

        # draw x grid lines. Every 5th is darker.
        for x in range(1, int(graph_x_max)+1):
            if x%5:
                color='grey90'
            else:
                color='grey75'
                # draw label
                self.graph.draw_text(f"{int(x)}\u00b0", (x, -0.3))
                self.graph.draw_text(f"{int(-x)}\u00b0", (-x, -0.3))

            self.graph.draw_line((x, graph_y_max), (x, -graph_y_max), color=color)
            self.graph.draw_line((-x, graph_y_max), (-x, -graph_y_max), color=color)

        # draw y grid lines. Every 5th is darker.
        for y in range(1, int(graph_y_max)+1):
            if y%5:
                color='grey90'
            else:
                color='grey75'
                # draw label
                self.graph.draw_text(f"{int(y)}\u00b0", (-0.3, y))
                self.graph.draw_text(f"{int(-y)}\u00b0", (-0.3, -y))
            self.graph.draw_line((-graph_x_max, y), (graph_x_max, y), color=color)
            self.graph.draw_line((-graph_x_max, -y), (graph_x_max, -y), color=color)

        clipx = lambda x: min(max(x, -graph_x_max), graph_x_max)
        clipy = lambda y: min(max(y, -graph_y_max), graph_y_max)

        rx = clipx(right_x)
        ry = clipy(right_y)
        lx = clipx(left_x) 
        ly = clipy(left_y)
        ldx = clipx(left_dpi_x)
        ldy = clipy(left_dpi_y)
        px = clipx(pupil_x) 
        py = clipy(pupil_y)

        # Only draw points for tracked eye(s)
        if self.state.calibration_eye in ("Right", "Both"):
            self.graph.draw_point((rx, ry), size=.15, color='firebrick1')
        if self.state.calibration_eye in ("Left", "Both"):
            if self.state.display_cr:
                self.graph.draw_point((lx, ly), size=.15, color='DodgerBlue')
            if self.state.display_dpi:
                self.graph.draw_point((ldx, ldy), size=.15, color='MediumSeaGreen')
        self.graph.draw_point((px, py), size=.15, color='DarkGoldenrod1')
        
        # int0 = self.state.last_eyes_data.extra.ints[0] & 1
        # int1 = self.state.last_eyes_data.extra.ints[1] & 1
        # self.graph.draw_point((4.3, -4.7), size=.30, color='green' if int0 else 'red')
        # self.graph.draw_point((4.7, -4.7), size=.30, color='green' if int1 else 'red')

    def update_raw_graph(self, raw_graph, measurements, highlight=[], sig='crsig'):
        """Draw raw measurements. sig is the CalibrationMeasurement signal to draw ('crsig' or 'dpisig')."""
        raw_graph.erase()
        raw_graph.draw_line((-100,-100), (-100,100))
        raw_graph.draw_line((-100,100),(100,100))
        raw_graph.draw_line((100,100), (100,-100))
        raw_graph.draw_line((100,-100), (-100,-100))
        for i, (key,pts) in enumerate(measurements.items()):
            for p in pts:
                # draw raw point
                s = getattr(p, sig)
                if not np.any(np.isnan(s)):
                    raw_graph.draw_point((s[0], s[1]), color=self.colorlist[i % len(self.colorlist)], size=4)
        # highlight should be a list of i,j tuples [(i0,j0),(i1,j1),...]
        for (key,ij) in highlight:
            pts = measurements[key]
            s = getattr(pts[ij[1]], sig)
            if not np.any(np.isnan(s)):
                raw_graph.draw_point((s[0], s[1]), color=self.colorlist[ij[0] % len(self.colorlist)], size=8)


    def update_cal_graph(self, cal_graph, measurements, cal, sig='crsig'):
        cal_graph.erase()
        cal_graph.draw_line((-5,0), (5,0))
        cal_graph.draw_line((0,-5), (0,5))
        cal_graph.draw_line((-5,-5), (-5,5))
        cal_graph.draw_line((-5,5), (5,5))
        cal_graph.draw_line((5,5),(5,-5))
        cal_graph.draw_line((5,-5),(-5,-5))
        cal_graph.draw_text('5V', (0.3,4.7), color='black')
        cal_graph.draw_text('5V', (4.7,0.3), color='black')
        cal_graph.draw_text('-5V', (-0.4,-4.7), color='black')
        cal_graph.draw_text('-5V', (-4.6,-0.3), color='black')
        for xy in range(-5, 6):
            cal_graph.draw_line((xy,-0.1), (xy,0.1))
            cal_graph.draw_line((-0.1,xy), (0.1,xy))

        for i, (key,pts) in enumerate(measurements.items()):
            for p in pts:
                s = getattr(p, sig)
                if np.any(np.isnan(s)):
                    continue
                pp = cal.transform(Point(s[0], s[1]))
                cal_graph.draw_point((pp.x, pp.y), color=self.colorlist[i % len(self.colorlist)], size=0.2)

    def update_calibration_graphs(self):
        """Called on timer to update calibration graphs.
        """

        if self.calibrator is not None:
            m = self.calibrator.measurements.copy()     # make copy in case something is added during write
            b, tempCal = self.calibrator.get_cal()
            bd, tempDpiCal = self.calibrator.get_dpi_cal()
            self.update_raw_graph(self.raw_graph, m, sig='crsig')
            self.update_cal_graph(self.cal_graph, m, tempCal, sig='crsig')
            self.update_raw_graph(self.raw_dpi_graph, m, sig='dpisig')
            self.update_cal_graph(self.cal_dpi_graph, m, tempDpiCal, sig='dpisig')
            # self.all_frames_in_text.update(self.state.frames_in)
            # self.calibration_frames_in_text.update(self.state.calibration_frames_in)
            # self.calibration_frames_out_text.update(self.state.calibration_frames_out)
            # self.calibration_frames_diff_text.update(self.state.calibration_frames_in - self.state.calibration_frames_out)

    def make_window(self):

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
        self.pupil_bias_factor = 1
        self.pupil_gain_factor = 1
        self.plb = GUIField(
            'LPupil Bias', 'left_pupil_bias', field_size, 
            self.state.pupil_cal, 'x_bias', gain_factor=self.pupil_bias_factor, 
            increment=1, multiplicative=False
            )
        # self.prb = GUIField(
        #     'Right Pupil Bias', 'right_pupil_bias', field_size, 
        #     self.state.pupil_cal, 'y_bias', gain_factor=self.pupil_bias_factor,
        #     increment=1, multiplicative=False
        #     )
        self.plg = GUIField(
            'LPupil Gain', 'left_pupil_gain', field_size, 
            self.state.pupil_cal, 'x_gain', gain_factor=self.pupil_gain_factor, 
            increment=0.05, multiplicative=True, flip_enabled=True,
            slider_enabled=True, slider_minimum=g_min, slider_maximum=g_max, slider_resolution=g_res
            )
        # self.prg = GUIField(
        #     'Right Pupil Gain', 'right_pupil_gain', field_size, 
        #     self.state.pupil_cal, 'y_gain', gain_factor=self.pupil_gain_factor,
        #     increment=0.05, multiplicative=True, flip_enabled=True,
        #     slider_enabled=True, slider_minimum=g_min, slider_maximum=g_max, slider_resolution=g_res
        #     )

        # CR (P1-P0) calibration fields, bound to left_cal
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
        self.cr_fields = [self.lbx, self.lby, self.lgx, self.lgy, self.lr]
         
        # DPI (P1-P4) calibration fields, bound to left_dpi
        self.dbx = GUIField(
            'X Bias', 'left_dpi_x_bias', field_size,
            self.state.left_dpi, 'x_bias', gain_factor=self.bias_factor,
            increment=.5, multiplicative=False,
            slider_enabled=True, slider_minimum=b_min, slider_maximum=b_max, slider_resolution=b_res
            )
        self.dby = GUIField(
            'Y Bias', 'left_dpi_y_bias', field_size,
            self.state.left_dpi, 'y_bias', gain_factor=self.bias_factor,
            increment=.5, multiplicative=False,
            slider_enabled=True, slider_minimum=b_min, slider_maximum=b_max, slider_resolution=b_res
            )
        self.dgx = GUIField(
            'X Gain', 'left_dpi_x_gain', field_size,
            self.state.left_dpi, 'x_gain', gain_factor=self.gain_factor,
            increment=0.05, multiplicative=True, flip_enabled=True,
            slider_enabled=True, slider_minimum=g_min, slider_maximum=g_max, slider_resolution=g_res
            )
        self.dgy = GUIField(
            'Y Gain', 'left_dpi_y_gain', field_size,
            self.state.left_dpi, 'y_gain', gain_factor=self.gain_factor,
            increment=0.05, multiplicative=True, flip_enabled=True,
            slider_enabled=True, slider_minimum=g_min, slider_maximum=g_max, slider_resolution=g_res
            )
        self.dr = GUIField(
            'Rotation', 'left_dpi_rotation', field_size,
            self.state.left_dpi, 'rotation', gain_factor=1,
            increment=1, multiplicative=False,
            slider_enabled=True, slider_minimum=-180, slider_maximum=180, slider_resolution=1
            )
        self.dpi_fields = [self.dbx, self.dby, self.dgx, self.dgy, self.dr]

        # which signals are drawn on the main graph. Both are always output.
        display_layout = [
            sg.Text('Display: '),
            sg.Checkbox('CR (P1-Pupil)', key='display_cr', default=self.state.display_cr, enable_events=True),
            sg.Checkbox('DPI (P1-P4)', key='display_dpi', default=self.state.display_dpi, enable_events=True)
            ]

        # max degrees in x and y. Degrees are used for coordinates/plotting in the main graph. The canvas size is in pixels.
        graph_x_max = MAX_VOLTS / self.state.calibration_vpdx
        graph_y_max = MAX_VOLTS / self.state.calibration_vpdy
        
        self.graph = sg.Graph(canvas_size=MAIN_GRAPH_CANVAS_SIZE, graph_bottom_left=(-graph_x_max, -graph_y_max), graph_top_right=(graph_x_max, graph_y_max), background_color='white', key='graph')
        self.cbmouse = sg.Checkbox("Mouse Mode", key='check-mouse-mode', enable_events=True, default=self.state.is_mouse_mode)

        graph_col = sg.Column([
            [sg.Text('', key='error', size=(20,1), text_color='red')],
            [self.graph],
            display_layout,
            [self.cbmouse]
            ])

        # this transform is used for converting raw mouse coordinates, which are in canvas pixel coordinates, into 
        # volts for output. This means we do not use graph_x_max,graph_y_max for the gain, but rather MAX_VOLTS.
        x_bias = -MAIN_GRAPH_CANVAS_SIZE[0]/2
        y_bias = -MAIN_GRAPH_CANVAS_SIZE[1]/2
        x_gain =  (2 * MAX_VOLTS)/MAIN_GRAPH_CANVAS_SIZE[0]
        y_gain = -(2 * MAX_VOLTS)/MAIN_GRAPH_CANVAS_SIZE[1]
        self.mouse_to_volts = CalibrationParameters(x_bias=x_bias, y_bias=y_bias, x_gain=x_gain, y_gain=y_gain, rotation=0)

        header_font = ('Helvetica', 14, 'bold')
        dd_col = sg.Column(
            [[sg.Text('CR', font=header_font)]] +
            [[f.get_layout()] for f in self.cr_fields] +
            [[sg.Button(' Zero ', key='left_zero', enable_events=True, button_color='DodgerBlue')]] +
            [[sg.Text('PUPIL', font=header_font)]] +
            [[self.plb.get_layout()]] +
            [[self.plg.get_layout()]],
            expand_y=True)

        dpi_col = sg.Column(
            [[sg.Text('DPI', font=header_font)]] +
            [[f.get_layout()] for f in self.dpi_fields] +
            [[sg.Button(' Zero ', key='left_dpi_zero', enable_events=True, button_color='MediumSeaGreen')]],
            expand_y=True)

        lt = sg.Tab('Left Eye', [[dd_col,dpi_col,graph_col]])

        self.output_list = list(self.state.output_dict.keys())
        self.output_list.insert(0, 'None')
        settings_layout = [
            [sg.Text('Channels: ')],

            # find each output list key in self.state.output_dict.keys()
            [sg.Text('CR X: '), sg.Combo(self.output_list, default_value=self.state.left_x_channel if self.state.left_x_channel in self.output_list else 'None', 
                                           key='left_x_channel', enable_events=True)],
            [sg.Text('CR Y: '), sg.Combo(self.output_list, default_value=self.state.left_y_channel if self.state.left_y_channel in self.output_list else 'None', 
                                            key='left_y_channel', enable_events=True)],
            [sg.Text('Pupil: '), sg.Combo(self.output_list, default_value=self.state.pupil_x_channel if self.state.pupil_x_channel in self.output_list else 'None', 
                                            key='pupil_x_channel', enable_events=True)],
            [sg.Text('DPI X: '), sg.Combo(self.output_list, default_value=self.state.left_dpi_x_channel if self.state.left_dpi_x_channel in self.output_list else 'None',
                                            key='left_dpi_x_channel', enable_events=True)],
            [sg.Text('DPI Y: '), sg.Combo(self.output_list, default_value=self.state.left_dpi_y_channel if self.state.left_dpi_y_channel in self.output_list else 'None',
                                            key='left_dpi_y_channel', enable_events=True)]
        ]
        st = sg.Tab('Settings', settings_layout)

        # tab for calibration plots

        header_font = ('Helvetica', 14, 'bold')
        self.raw_graph = sg.Graph(canvas_size=RAW_GRAPH_CANVAS_SIZE, graph_bottom_left=RAW_GRAPH_BOTTOM_LEFT, graph_top_right=RAW_GRAPH_TOP_RIGHT, background_color='white', key='cal-raw-cr')
        self.cal_graph = sg.Graph(canvas_size=CAL_GRAPH_CANVAS_SIZE, graph_bottom_left=CAL_GRAPH_BOTTOM_LEFT, graph_top_right=CAL_GRAPH_TOP_RIGHT, background_color='white', key='cal-fit-cr')
        cr_column = sg.Column([[sg.Text('CR', font=header_font)],[self.raw_graph],[self.cal_graph]], element_justification='center')

        self.raw_dpi_graph = sg.Graph(canvas_size=RAW_GRAPH_CANVAS_SIZE, graph_bottom_left=RAW_GRAPH_BOTTOM_LEFT, graph_top_right=RAW_GRAPH_TOP_RIGHT, background_color='white', key='cal-raw-dpi')
        self.cal_dpi_graph = sg.Graph(canvas_size=CAL_GRAPH_CANVAS_SIZE, graph_bottom_left=CAL_GRAPH_BOTTOM_LEFT, graph_top_right=CAL_GRAPH_TOP_RIGHT, background_color='white', key='cal-fit-dpi')
        dpi_column = sg.Column([[sg.Text('DPI', font=header_font)],[self.raw_dpi_graph],[self.cal_dpi_graph]], element_justification='center')

        # second column for other stuff.
        other_column = sg.Column([[sg.Button('Try to fit', key='do-cal-fit', enable_events=True, button_color='PaleVioletRed4')],
                                  [sg.Button('Edit points', key='cal-edit-points', enable_events=True, button_color='PaleVioletRed4')],
                                  [sg.Button('Accept fit', key='cal-accept', enable_events=True, button_color='PaleVioletRed4')],
                                  [sg.Button('Clear', key='cal-clear', enable_events=True, button_color='PaleVioletRed4')]])
        calibration_layout = [[cr_column,dpi_column,other_column]]
        ct = sg.Tab('Calibration', calibration_layout)

        tabs = sg.TabGroup([[lt,ct,st]], key='tabs', expand_y=True)
        
        self.layout = [
            [sg.Menu(menu_def)],
            [tabs],
            [sg.StatusBar('Status', key='statusbar', size=(100,1))]
        ]

        window = sg.Window('OpenIrisClient', self.layout, finalize=True)
        return window

    def window_loop(self, verbose=False, subject=None):

        # Allow user to select a configuration
        # TODO: Remember configuration used last time this program ran.
        if not subject:
            subject = GlobalState.select_subject()
        logger.info(f"Got subject {subject}")
        if not subject:
            self.state.is_running = False
        else:
            self.state.load_config(subject=subject)

        # Make window here. This ensures that the loaded config is the one in the window
        self.window = self.make_window()
        first = True

        while self.state.is_running:
            event, values = self.window.read(timeout=20) # 20ms = 50Hz
            # if event != '__TIMEOUT__':
            #     print(event, values)
            if first:
                self.graph.bind('<Motion>', '-mouse-motion')
                self.update_output_channels()
                self.update_sliders()
                first = False
            if verbose and event != sg.TIMEOUT_EVENT:
                logger.info(event, values)

                        # update status bar
            if event == sg.TIMEOUT_EVENT:
                self.window['statusbar'].update(f"{'Calibrating' if self.state.calibrating else 'Running'} : {self.state.subject} : frames in {self.state.frames_in} : rate {self.state.frames_in/(time.monotonic() - self.state.frames_start_time):>3.1f} fps : missed {self.state.frames_missed}")

            # handle exit
            if event == sg.WIN_CLOSED or event == 'Close' or event == 'Exit':
                self.state.is_running = False
                break
            
            # Update which signals are displayed on the main graph
            if event in ['display_cr', 'display_dpi']:
                self.state.display_cr = values['display_cr']
                self.state.display_dpi = values['display_dpi']

            # Update states
            self.lbx.update(self.window, event, values)
            self.lby.update(self.window, event, values)
            self.lgx.update(self.window, event, values)
            self.lgy.update(self.window, event, values)
            self.lr.update(self.window, event, values)
            self.plb.update(self.window, event, values)
            self.plg.update(self.window, event, values)
            for f in self.dpi_fields:
                f.update(self.window, event, values)

            # checkbox? 
            if event == "check-mouse-mode":
                logger.info(f"check-mouse-mode {self.cbmouse.get()}")
                self.state.is_mouse_mode = self.cbmouse.get()
                if self.state.is_mouse_mode:
                    self.graph.update(background_color = 'yellow')

                else:
                    self.graph.update(background_color = 'white')

            # mouse mode. The mouse event xy value is in graph pixels. The transform is for converting it to 
            # degrees. 
            if event == 'graph-mouse-motion':
                if self.state.is_mouse_mode:
                    e = self.graph.user_bind_event
                    self.state.mouse_mode_xy = self.mouse_to_volts.transform(Point(e.x, e.y))
                    # logger.info(f"graph-mouse-motion {e.x},{e.y} -> {self.state.mouse_mode_xy.x}, {self.state.mouse_mode_xy.y}")

                # print(e)

            # Update output channels
            if event in ['left_x_channel', 'left_y_channel', 'right_x_channel', 'right_y_channel', 'pupil_x_channel', 'pupil_y_channel',
                         'left_dpi_x_channel', 'left_dpi_y_channel']:
                self.update_output_channels()

            # Zero left CR (P1-pupil)
            if event == 'left_zero':
                last_left = self.state.last_eyes_data.left.cr - self.state.last_eyes_data.left.pupil
                self.state.left_cal.x_bias = -last_left.x
                self.state.left_cal.y_bias = -last_left.y
                logger.info(f"Zero CR: bias {self.state.left_cal.x_bias}, {self.state.left_cal.y_bias}")
                self.lbx.sync_state(self.window)
                self.lby.sync_state(self.window)

            # Zero left DPI (P1-P4)
            if event == 'left_dpi_zero':
                last_left = self.state.last_eyes_data.left.cr - self.state.last_eyes_data.left.p4
                self.state.left_dpi.x_bias = -last_left.x
                self.state.left_dpi.y_bias = -last_left.y
                logger.info(f"Zero DPI: bias {self.state.left_dpi.x_bias}, {self.state.left_dpi.y_bias}")
                self.dbx.sync_state(self.window)
                self.dby.sync_state(self.window)

            
            # Zero right
            if event == 'right_zero':
                pass

            # Switch left and right
            if event == 'switch':
                pass

            # Save config
            # if event == 'Save Config':
            #     # Open a dialog to select a new file
            #     save_dir = sg.popup_get_folder('Select save directory', default_path=self.state.save_dir)
            #     self.state.save(Path(save_dir))

            # Load config
            if event == 'Load Config':

                subject = GlobalState.select_subject()
                logger.info(f"Got subject {subject}")
                if subject:
                    self.state.load_config(subject=subject)
                    self.window.close()
                    self.window = self.make_window()
                    first = True

                # # Open a folder picking dialog
                # load_dir = sg.popup_get_folder('Select directory to load', default_path=self.state.save_dir)
                # if load_dir:
                #     self.state.load(Path(load_dir))
                #     self.update_sliders()


            if self.calibrator is not None:
                if event == 'cal-edit-points':
                    b, m = self.edit_points(self.calibrator.measurements)
                    if b:
                        self.calibrator.measurements = m

                if event == 'do-cal-fit':
                    self.calibrator.dofit()

                if event == 'cal-clear':
                    self.calibrator.clear_cal()
                    self.update_calibration_graphs()

                if event == 'cal-accept':
                    # accept each valid fit into its own calibration: CR -> left_cal, DPI -> left_dpi
                    accepted = False
                    for name, (b, cal), target in (('CR', self.calibrator.get_cal(), self.state.left_cal),
                                                   ('DPI', self.calibrator.get_dpi_cal(), self.state.left_dpi)):
                        if b:
                            with cal_lock:
                                target.x_bias = cal.x_bias
                                target.y_bias = cal.y_bias
                                target.x_gain = cal.x_gain
                                target.y_gain = cal.y_gain
                                target.rotation = cal.rotation
                            logger.info(f"Accepted {name} fit: {cal}")
                            accepted = True
                    if accepted:
                        self.update_sliders()   # updates calibration values in gui. Output
                    else:
                        logger.error(f"Calibrator does not have a valid calibration.")

                # if event == 'cal-load':
                #     file_to_load = sg.popup_get_file('Select a cal-xy file to load', initial_folder=str(self.state.data_path), file_types=(('xy files', '.xy'),), no_window=True)
                #     # Build a list of tuples for each file type the file dialog should display
                #     if file_to_load:
                #         self.calibrator.load_measurements(file_to_load)

                # update calibration graphs
                if event == 'calibration-graphs':
                    self.update_calibration_graphs()

            # update graph and errors on timeout (refresh)
            if event == sg.TIMEOUT_EVENT:
                self.update_graph()
                self.update_calibration_graphs()    # TEMP HACK

                # Get eye data error, if any
                error = self.state.last_eyes_data.get_error(left_p4=self.state.display_dpi, right_p4=True)
                if error:
                    self.window['error'].update(value = error, text_color='red')
                else:
                    self.window['error'].update(value = 'Tracking', text_color='lawn green')

    def edit_points(self, measurements):

        # work with a copy
        tmpmeas = copy.deepcopy(measurements)

        # dialog stuff
        graph = sg.Graph(
                    canvas_size=RAW_GRAPH_CANVAS_SIZE, graph_bottom_left=RAW_GRAPH_BOTTOM_LEFT, graph_top_right=RAW_GRAPH_TOP_RIGHT,   # Define the graph area
                    change_submits=True,    # mouse click events
                    background_color='white',
                    key="edit-graph",
                    pad=0)
        delButton = sg.Button('Delete Selected', key='delete-selected', enable_events=True)
        clearButton = sg.Button('Clear Selection', key='clear-selected', enable_events=True)
        cancelButton = sg.Button('Cancel', key='cancel-edit', enable_events=True)
        okButton = sg.Button('OK', key='ok-edit', enable_events=True)
        buttons=[delButton, clearButton, cancelButton, okButton]

        # find point in meas closest to given x,y        
        def closest_point(xms,yms,meas):
            keyclose=(-1,-1)
            iclose=-1
            jclose=-1
            dsqmin=999999999
            for i, (key,pts) in enumerate(meas.items()):
                for j,p in enumerate(pts):
                    dsq = (xms-p.crsig[0])**2+(yms-p.crsig[1])**2
                    if dsq < dsqmin:
                        keyclose=key
                        iclose=i
                        jclose=j
                        dsqmin=dsq
            return keyclose, (iclose, jclose)

        # delete points in del_list. 
        # del list has tuples. Each tuple has a key and an int. The key finds the
        # array in meas, the int is the index to pop.
        def delete_points(meas, del_list):
            # sort in reverse, then delete in place
            rev = sorted(del_list, reverse=True)
            for (key,j) in rev:
                meas[key].pop(j[1])
            return meas

        def count_meas(meas):
            n=0
            for key,pts in meas.items():
                n+=len(pts)
            return n

        layout = [[graph],buttons]
        window = sg.Window("Edit points", layout, finalize=True, margins=(0,0))
        self.update_raw_graph(graph, tmpmeas )
        bDirty = True
        selected_list=[]
        bOK = False
        while True:
            event, values = window.read(timeout=20)
            if event == sg.WIN_CLOSED:
                break
            #print(event, values) if event != sg.TIMEOUT_EVENT else None # our normal debug print, but for this demo, don't spam output with timeouts

            if event == "edit-graph":  # if there's a "Graph" event, then it's a mouse movement. Move the square
                xmouse, ymouse = values["edit-graph"]        # get mouse position
                # find closest point and highlight it
                k,ij = closest_point(xmouse, ymouse, tmpmeas )
                #logger.info(f"clicked at {xmouse}, {ymouse}, selected {k},{ij}")
                selected_list.append((k,ij))
                bDirty = True
            elif event == "clear-selected":
                selected_list.clear()
                bDirty = True
            elif event == "delete-selected":
                delete_points(tmpmeas , selected_list)
                selected_list.clear()
                bDirty = True
            elif event == "cancel-edit":
                bOK = False
                break
            elif event == "ok-edit":
                bOK = True
                break
            if event == sg.TIMEOUT_EVENT:
                if bDirty:
                    self.update_raw_graph(graph, tmpmeas , selected_list)
                    bDirty = False

                # enable/disable
                if len(selected_list)>0:
                    pass
                    #enable DELETE button

        window.close()
        return bOK, tmpmeas 


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




if __name__ == "__main__":
    from threading import Thread

    logging.basicConfig(level=logging.INFO)

    # Single input argument (optional) is filename to write output to.
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", help="File to write output to", type=str, default='')
    parser.add_argument("--fake", help="Use fake data generator instead of OpenIrisClient", action='store_true')
    parser.add_argument("--fake-speed", help="Fake data: gaze speed along Lissajous path, deg/s", type=float, default=2.0)
    parser.add_argument("--fake-cr-noise", help="Fake data: CR noise amplitude, deg", type=float, default=0.05)
    parser.add_argument("--fake-dpi-noise", help="Fake data: DPI noise amplitude, deg", type=float, default=0.05)
    parser.add_argument("--address", help="Address of OpenIrisServer", default='localhost')
    parser.add_argument("--port", help="Port of OpenIrisServer", default=9003, type=int)
    parser.add_argument("--cal-port", help="Port of calibrator server", default=9292, type=int)
    parser.add_argument("--fps", help="Capture rate, in frames per second, of eye tracker.", type=int, default=0)
    parser.add_argument("--eye", help="Eye to calibrate from. If single camera, configure it correctly. If dual, then this must be specified.", type=str, default='')
    parser.add_argument("--tracker-folder", help="Folder with the EyeTrackerSettings.xml file", type=str, default='')
    parser.add_argument("--subject", help="Current subject (part of path to config file)", type=str, default=None)
    args = parser.parse_args()

    # # if no subject was specified, open selection dialog
    # if not args.subject:
    #     subject = GlobalState.select_subject()    
    #     print(f"Selected subject {subject}")

    print(f"args.subject: {str(args.subject)}")
    if not args.fake:
        kwargs = {'server_address': args.address, 'port': args.port}
    else:
        logger.warning('Using fake data generator')
        kwargs = {}

    gs = GlobalState()

    # get fps and eye if not on command line. With --fake there is no tracker, so use defaults.
    if args.fake:
        (capture_fps, calibration_eye) = (500, 'Left')
    elif not (args.fps and args.eye):
        ets = EyeTrackerSettings(tracker_folder=args.tracker_folder)
        (capture_fps, calibration_eye) = ets.get_frame_rate()
    if not args.fps:
        gs.capture_fps = capture_fps
    else:
        gs.capture_fps = args.fps
    if not args.eye:
        gs.calibration_eye = calibration_eye
    else:
        gs.calibration_eye = args.eye
    logger.info(f"Using {gs.calibration_eye} eye for calibration.")
    logger.info(f"Using capture frame rate of {gs.capture_fps}fps for calibration measurements")

    # create a generator for the pipeline
    if args.fake:
        generator = FakeEyeDataGenerator(gs, speed_deg_per_sec=args.fake_speed,
                                         cr_noise_deg=args.fake_cr_noise, dpi_noise_deg=args.fake_dpi_noise)
    else:  
        generator = OpenIrisClientGenerator(gs, args.address, args.port)


    # start calibrator server if specified
    calibrator_comm_thread = None
    calibrator_ana_thread = None
    dio_thread = None
    dio_stop_event = None
    if args.cal_port:
        calibrator_comm_thread = CalibratorComm(gs, port=args.cal_port)
        calibrator_comm_thread.start()
        calibrator_ana_thread = Calibrator(gs)
        calibrator_ana_thread.start()
        dio_stop_event = Event()
        dio_thread = DIOThread(dio_stop_event, gs)
        dio_thread.start()

    gui_thread = Thread(target=GUI(gs, calibrator_ana_thread).window_loop, args=(False,args.subject))
    gui_thread.start()

    # start data pipeline
    dp_thread = Thread(target=DataPipeline(gs, generator).run, args=(False,))
    dp_thread.start()
    gs.is_running = True

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
    gs.save_config()
    