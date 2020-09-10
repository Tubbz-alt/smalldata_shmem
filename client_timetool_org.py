import sys
import zmq
import traceback
import yaml

import numpy as np
import holoviews as hv
import pandas as pd

from bokeh.layouts import layout, widgetbox, row, column
from bokeh.models import Button, Slider, Select, HoverTool, DatetimeTickFormatter
from bokeh.plotting import curdoc
from bokeh.io import output_file, save
from bokeh.server.server import Server
from bokeh.application import Application
from bokeh.application.handlers.function import FunctionHandler
from holoviews.core import util
import tables
from functools import partial
from collections import deque
import datetime

renderer = hv.renderer('bokeh').instance(mode='server')

def apply_formatter(plot, element):
    """
    Datetime formatting for x-axis ticks 
    
    """
    
    plot.handles['xaxis'].formatter = DatetimeTickFormatter(
        microseconds=['%D %H:%M:%S'], 
        milliseconds=['%D %H:%M:%S'], 
        seconds=["%D %H:%M:%S"],
        minsec=["%D %H:%M:%S"],
        minutes=['%D %H:%M:%S'], 
        hourmin=["%D %H:%M:%S"],
        hours=['%D %H:%M:%S'],
        days=['%D %H:%M:%S'], 
        months=['%D %H:%M:%S'], 
        years=['%D %H:%M:%S'])


def my_partial(func, *args, **kwargs):
    """
    Modified partial function from functools without type check
    
    Needed for Python 2.7 since 2.7 cannot recognize that hv.Elements
    are callable
    
    """
    
    def wrap(*args, **kwargs):
        return func(*args, **kwargs)
    return partial(wrap, *args, **kwargs)
    
class BokehApp:
    
    def __init__(self):
        setupDict=yaml.load(open('smalldata_plot.yml','r'))
        self.master_port=setupDict['master']['port']
        self.master_server=setupDict['master']['server']
        self.plotName=plotName

        self.updateRate=setupDict[self.plotName]['updateRate']
        self.number_of_events = setupDict[self.plotName]['number_of_events']
        self.plot_width=setupDict[self.plotName]['width']
        self.plot_height=setupDict[self.plotName]['height']
        self.yRange=setupDict[self.plotName]['yRange']

        self.i0var=setupDict[self.plotName]['i0var']
        
        # Initialize buffers
        self.b_timetool = hv.streams.Stream.define('df_tt',df_tt=pd.DataFrame({'timestamp': [], 'timetool': []}))
        self.b_IpmAmp = hv.streams.Stream.define('df_it',df_it=pd.DataFrame({'timetool': [], 'ipm': []}))
        self.b_corr_timehistory = hv.streams.Stream.define('df_tc',df_tc=pd.DataFrame({'timestamp':[],'correlation':[]}))
        
        # Initialize callbacks
        self.cbid_timetool = None
        self.cbid_amp_ipm = None
        self.cbid_corr_timehistory = None

                    
    def produce_graphs(self, context, doc):
        """
        Create timetool data timehistory, timetool vs ipm, 
        and correlation timehistory graphs.
        
        Parameters
        ----------
        
        context = zmq.Context()
            Creates zmq socket to receive data
            
        doc: bokeh.document (I think)
            Bokeh document to be displayed on webpage
        
        """

        socket = context.socket(zmq.REQ)        
        socket.connect("tcp://%s:%d" %(self.master_server,self.master_port))
        
        # Note: Cannot name 'timetool' variables in hvTimeTool and hvIpmAmp the same thing
        # Otherwise, holoviews will try to sync the axis and throw off the ranges for the plots
        # since hvIpmAmp only deals with the last 1000 points whereas hvTimeTool deals with all
        # the points
        hvTimeTool = hv.DynamicMap(
            my_partial(hv.Points, kdims=['timestamp', 'timetool']), streams=[self.b_timetool]).options(
            width=self.plot_width, finalize_hooks=[apply_formatter], xrotation=45).redim.label(
            timestamp='Time in UTC', timetool='Timetool Data')
        
        hvIpmAmp = hv.DynamicMap(
            my_partial(hv.Scatter, kdims=['timetool', 'ipm']), streams=[self.b_IpmAmp]).options(
                width=int(self.plot_width/2.)).redim.label(
            timetool='Last 1000 Timetool Data Points', ipm='Last 1000 Ipm Data Points')
        
        hvCorrTimeHistory = hv.DynamicMap(
            my_partial(hv.Scatter, kdims=['timestamp', 'correlation']), streams=[self.b_corr_timehistory]).options(
            width=int(self.plot_width/2), finalize_hooks=[apply_formatter], xrotation=45).redim.label(
            time='Time in UTC')

        layout = (hvIpmAmp+hvCorrTimeHistory+hvTimeTool).cols(2)
        hvplot = renderer.get_plot(layout)

        def request_data_timetool(buffer):
            """
            Push data to timetool time history graph
            
            """
            socket.send_string("Request_%s"%self.plotName.replace(' ','_'))
            nowStr = time.strftime("%b %d %Y %H:%M:%S", time.localtime())
            print("Timetool requested data at %s, plot %g seconds "%(nowStr,time.time()-self.plotStartTime))

            data_dict = socket.recv_pyobj()

            timetool_d = deque(maxlen=self.number_of_events)
            timetool_t = deque(maxlen=self.number_of_events)

            timetool_d = data_dict['tt__FLTPOS_PS']

            # Get time from data_dict
            timeData = deque(maxlen=self.number_of_events)
            for time in data_dict['event_time']:
                num1 = str(time[0])
                num2 = str(time[1])
                fullnum = num1 + "." + num2
                timeData.append(float(fullnum))
            timetool_t = timeData

            # Convert time to seconds so bokeh formatter can get correct datetime
            times = [1000*time for time in list(timetool_t)]

            data = pd.DataFrame({'timestamp': times, 'timetool': timetool_d})
                        
            buffer.send(data)
            
        def request_data_amp_ipm (buffer):
            """
            Push data into timetool amp vs ipm graph
            
            """
            socket.send_string("Request_%s"%self.plotName.replace(' ','_'))
            nowStr = time.strftime("%b %d %Y %H:%M:%S", time.localtime())
            print("Timetool ampl-ipm requested data at %s, plot %g seconds "%(nowStr,time.time()-self.plotStartTime))
            data_dict = socket.recv_pyobj()
        
            timetool_d = deque(maxlen=self.number_of_events)
            ipm_d = deque(maxlen=self.number_of_events)

            timetool_d = data_dict['tt__AMPL']
            ipm_d = data_dict[self.i0var]

            data = pd.DataFrame({'timetool': timetool_d, 'ipm': ipm_d})

            buffer.send(data)
            
        def request_data_corr_time_history(buffer):
            """
            Calculate correlation between timetool amp and ipm and
            push to correlation time history graph
            
            """
            socket.send_string("Request_%s"%self.plotName.replace(' ','_'))
            nowStr = time.strftime("%b %d %Y %H:%M:%S", time.localtime())
            print("Timetool corr_time requested data at %s, plot %g seconds "%(nowStr,time.time()-self.plotStartTime))
            data_dict = socket.recv_pyobj()
        
            timetool_d = deque(maxlen=self.number_of_events)
            timetool_t = deque(maxlen=self.number_of_events)
            ipm_d = deque(maxlen=self.number_of_events)

            timetool_d = data_dict['tt__FLTPOS_PS']
            ipm_d = data_dict[self.i0var]

            # Get time from data_dict
            timeData = deque(maxlen=self.number_of_events)
            for time in data_dict['event_time']:
                num1 = str(time[0])
                num2 = str(time[1])
                fullnum = num1 + "." + num2
                timeData.append(float(fullnum))
            timetool_t = timeData

            # Convert time to seconds so bokeh formatter can get correct datetime
            times = [1000*time for time in list(timetool_t)]

            data = pd.DataFrame({'timetool': timetool_d, 'ipm': ipm_d})
            data_corr = data['timetool'].rolling(window=120).corr(other=data['ipm'])

            # Start at index 119 so we don't get null data
            final_df = pd.DataFrame({
                'timestamp': times[119:], 
                'correlation': data_corr[119:]
            })

            buffer.send(final_df)
                    
        
        def stop():
            """
            Add pause and play functionality to graph
            
            """
            
            if stopButton.label == 'Play':
                stopButton.label = 'Pause'
                self.cb_id_timetool = doc.add_periodic_callback(
                    partial(request_data_timetool, 
                            buffer=self.b_timetool), 
                    1000)

                self.cb_id_amp_ipm = doc.add_periodic_callback(
                    partial(request_data_amp_ipm,
                            buffer=self.b_IpmAmp), 
                    1000)

                self.cb_id_corr_timehistory = doc.add_periodic_callback(
                    partial(requeset_data_corr_time_history, 
                            buffer=self.b_corr_timehistory), 
                    1000)
            else:
                stopButton.label = 'Play'
                doc.remove_periodic_callback(self.cb_id_timetool)
                doc.remove_periodic_callback(self.cb_id_amp_ipm)
                doc.remove_periodic_callback(self.cb_id_corr_timehistory)
        
        # Start the callback
        self.cb_id_timetool = doc.add_periodic_callback(
            partial(push_data_timetool, 
                    buffer=self.b_timetool), 
            1000)

        self.cb_id_amp_ipm = doc.add_periodic_callback(
            partial(push_data_amp_ipm,
                    buffer=self.b_IpmAmp), 
            1000)

        self.cb_id_corr_timehistory = doc.add_periodic_callback(
            partial(push_data_corr_time_history, 
                    buffer=self.b_corr_timehistory), 
            1000)
        
        
        stopButton = Button(label='Pause')
        stopButton.on_click(stop)
        
        plot = column(stopButton, hvplot.state)
        doc.add_root(plot)
        
def make_document(context, doc):
    """
    Create an instance of BokehApp() for each instance of the server
    
    """
    
    bokehApp = BokehApp()
    
    bokehApp.produce_graphs(context, doc)
    
def launch_server():
    """
    Launch a bokeh_server to plot the a timetool time history, timetool amp
    vs ipm, and correlation graph by using zmq to get the data.
    
    """
   
    context = zmq.Context()

    origins = ["localhost:{}".format(5000)]
    
    apps = {'/': Application(FunctionHandler(partial(make_document, context)))}
    server = Server(apps, port=5000)
    
    server.start()
    
    print('Opening Bokeh application on:')
    for entry in origins:
        print('\thttp://{}/'.format(entry))
 
    try:
        server.io_loop.start()
    except KeyboardInterrupt:
        print("terminating")
        server.io_loop.stop()
        
        
if __name__ == '__main__':
    launch_server()
