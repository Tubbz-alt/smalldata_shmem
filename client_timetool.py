import sys
import zmq
import traceback
import yaml
import time

import numpy as np
import holoviews as hv
import pandas as pd

from bokeh.layouts import layout, widgetbox, row, column
from bokeh.models import DatetimeTickFormatter
from bokeh.plotting import curdoc
from bokeh.server.server import Server
from bokeh.application import Application
from bokeh.application.handlers.function import FunctionHandler
from holoviews.core import util
from functools import partial

renderer = hv.renderer('bokeh').instance(mode='server')

def my_partial(func, *args, **kwargs):
    """
    Modified partial function from functools without type check
    
    Needed for Python 2.7 since 2.7 cannot recognize that hv.Elements
    are callable
    
    """
    
    def wrap(*args, **kwargs):
        return func(*args, **kwargs)
    return partial(wrap, *args, **kwargs)

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

    
def gen_plot(df, yRange=None):
    """
    Return holoviews plot
    
    Parameters
    ----------
    
    df: pandas.DataFrame
        DataFrame containing data to be plotted
    
    """
    
    # Get bounds for graph
    colNames = list(df)
    if yRange==None or yRange[0]=='auto':
        lowY = df[colNames[0]].quantile(0.01)
        highY = df[colNames[0]].quantile(0.99)
    else:
        lowY = yRange[0]
        highY = yRange[1]

    lastTime = df[colNames[0]].last_valid_index()
    dateStr = time.strftime("%b %d %Y %H:%M:%S", time.localtime(lastTime))

    if df.shape[0]>0:
        scatterSize=max(1,5-int(np.log(df.shape[0])/2.))
        #print(scatterSize, int(np.log(df.shape[0])/2.), np.log(df.shape[0]))
    else:
        scatterSize=5.
    scatter=hv.Scatter(df, group="Number of events: %d at %s"%(len(df.index), dateStr) ).redim.range(**{df.columns[0]:(lowY, highY)}).opts(norm=dict(framewise=True)).options(size=scatterSize)
    #no mean for this plot.
    #print('hist: ',df.hist(bins=100))
    #hst=hv.Curve(df.hist(bins=100)).opts(norm=dict(framewise=True))
    #return (scatter+hisPlt).cols(1)
    return scatter

class BokehApp:
    
    def __init__(self, plotName):
        self.plotStartTime = time.time()        

        setupDict=yaml.load(open('smalldata_plot.yml','r'))
        self.master_port=setupDict['master']['port']
        self.master_server=setupDict['master']['server']
        self.plotName=plotName

        self.updateRate=setupDict[self.plotName]['updateRate']
        self.number_of_events = setupDict[self.plotName]['number_of_events']
        self.plot_width=setupDict[self.plotName]['width']
        self.plot_height=setupDict[self.plotName]['height']
        self.yRange=setupDict[self.plotName]['yRange']

        self.var1='tt__FLTPOS'
        self.data={self.var1:[]}
        # Initialize buffers
        self.streamData = hv.streams.Stream.define('df',df=pd.DataFrame(self.data))()
                    
    def produce_plot(self, context, doc, plotName):
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
        gen_Plot = my_partial(gen_plot, yRange=self.yRange)
        #plotScat = hv.DynamicMap(gen_Plot, streams=[self.streamData]).options(width=self.plot_width, height=self.plot_height, finalize_hooks=[apply_formatter] )#.redim.label(timestamp='Time in UTC', timetool='Timetool Data')
        plotScat = hv.DynamicMap(gen_Plot, streams=[self.streamData]).options(width=self.plot_width, height=self.plot_height)
                
        hvplot = renderer.get_plot(plotScat, doc)
        #layout = ( plotScat ).cols(1)
        #hvplot = renderer.get_plot(layout, doc)

        def request_data():
            """
            Push data to timetool time history graph
            
            """
            socket.send_string("Request_%s"%self.plotName.replace(' ','_'))
            nowStr = time.strftime("%b %d %Y %H:%M:%S", time.localtime())
            print("Timetool requested data at %s, plot %g seconds "%(nowStr,time.time()-self.plotStartTime))

            data_dict = socket.recv_pyobj()

            pdSeriesDict={}

            # FIX ME: why this?
            # Get time from data_dict
            timeData = data_dict['event_time'][-self.number_of_events:]
            modTimeData = timeData[:,0]+ (timeData[:,1]*1e-6).astype(int)*1e-3

            for key in self.data.keys():
                pdSeriesDict[key]= pd.Series(
                     data_dict[key][-self.number_of_events:],
                     index=modTimeData)
            full_frame = pd.DataFrame(pdSeriesDict)

            self.streamData.event(df=full_frame)
                    
        self.callback_id = doc.add_periodic_callback(request_data, self.updateRate*1000.)

        plot = layout([hvplot.state])
        doc.title = "%s vs time"%(self.var1)
        doc.add_root(plot)
        
def make_document(context, plotName, doc):
    """
    Create an instance of BokehApp() for each instance of the server
    
    """
    
    bokehApp = BokehApp(plotName)
    
    bokehApp.produce_plot(context, doc, plotName)
    
    
def launch_server(plotName):
    """
    Launch a bokeh_server to plot the a timetool time history, timetool amp
    vs ipm, and correlation graph by using zmq to get the data.
    
    """
   
    setupDict=yaml.load(open('smalldata_plot.yml','r'))
    plotDict=setupDict[plotName]
   
    context = zmq.Context()

    origins = ["localhost:{}".format(plotDict['port'])]
    
    apps = {'/': Application(FunctionHandler(partial(make_document, context, plotName)))}
    server = Server(apps, port=plotDict['port'])
    
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
    plotName=None
    if len(sys.argv)<2:
        print('you need to pass the name of the plot!')
    launch_server(sys.argv[1])
