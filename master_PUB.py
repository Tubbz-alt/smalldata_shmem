from mpi4py import MPI
comm = MPI.COMM_WORLD
rank = comm.Get_rank()
size = comm.Get_size()

import numpy as np
from mpidata import mpidata 
import zmq
import random
import sys
import time
import yaml
import socket
import os

from threading import Thread
#import RegDB.experiment_info
#
# I need two loops: one listens to the clients and appends to the master dict
# the other loop listens for requests and sends data if asked for,
#

# Only make socket and connection once

def runmaster(nClients):

    setupDict=yaml.load(open('smalldata_plot.yml','r'))
    master_port=setupDict['master']['port']

    context = zmq.Context()
    socket = context.socket(zmq.PUB)
    socket.bind("tcp://*:%s" % master_port)

    myDict={'runNumber':-1}

    hutches=['amo','sxr','xpp','xcs','mfx','cxi','mec']
    hutch=None
    print('master_PUB pre pre hostname')
    import socket as skt
    hostname=skt.gethostname()
    print('master_PUB post pre hostname')
    #hostname=socket.gethostname() #this is a problem now - not interactively...WHY?
    #print('master_PUB post hostname')
    for thisHutch in hutches:
        if hostname.find(thisHutch)>=0:
            hutch=thisHutch.upper()
    if hutch is None:
        #then check current path
        path=os.getcwd()
        for thisHutch in hutches:
            if path.find(thisHutch)>=0:
                hutch=thisHutch.upper()
    if hutch is None:
        print('cannot figure out which hutch we are in to use. resetting at end of run will not work')

    #main "thread" to get the MPI data and append it to the dict.
    nDataReceived=0
    print('About to start the while loop for the master process w/ %d clients'%nClients)
    while nClients > 0:
        print('MASTER got data: ',nDataReceived)
        nDataReceived+=1
        ##get current run number & reset if new. Put into thread?
        ##here, I'm resetting the master dict on a new run. For now, this is not exactly how this should run.
        ##need to maybe use a deque for the jet tracking? Figure out much later how to combine...
        #if hutch is not None and nDataReceived%(size-1)==(size-2):
        #    lastRun = RegDB.experiment_info.experiment_runs(hutch)[-1]['num'] 
        #    #if the run number has changed, reset the master dictionary & set the new run number.
        #    if lastRun != myDict['runNumber']:
        #        print('Reset master dict, new run number: %d'%lastRun)
        #        myDict.clear()
        #        myDict['runNumber']=lastRun

        # Remove client if the run ended
        md = mpidata()
        md.recv()
        ##ideally, there is a reset option from the bokeh server, but we can make this 
        ##optional & reset on run boundaries instead/in addition.
        if md.small.endrun: #what if going from just running to recording?
            print('ENDRUN!')
            #nClients -= 1 #No...
            myDict.clear()
            myDict['runNumber']=lastRun
        else:
            print('DEBUG: master: ', md.nEvts)   
            #append the lists in the dictionary we got from the clients to a big master dict.
            for mds in md.small.arrayinfolist:
                #print 'mds name: ',mds.name
                if mds.name not in myDict.keys():
                    myDict[mds.name]=getattr(md, mds.name)
                else:
                    myDict[mds.name]=np.append(myDict[mds.name], getattr(md, mds.name), axis=0)
            #check if dict is aligned
            for mds in md.small.arrayinfolist:
                if mds.name=='nEvts': continue
                if mds.name=='send_timeStamp': continue
                if myDict[mds.name].shape[0]!=myDict['event_time'].shape[0]:
                    print('We are out of alignment for %s '%mds.name, myDict[mds.name].shape[0],  myDict['event_time'].shape[0])

            #md.addarray('evt_ts',np.array(evt_ts))
            evt_ts_str = '%.4f'%(md.send_timeStamp[0] + md.send_timeStamp[1]/1e9)
            #here we will send the dict (or whatever we make this here) to the plots.
            print('master data: ', myDict.keys())
            print('master has events: ', myDict['lightStatus__xray'].shape)

            #
            # this is if we send data off via ZMQ.
            #
            #print("smallData master received request: ", message)
            #if len(dict_to_send.keys())>0:
            #    print("smallData master will send : ", dict_to_send['lightStatus__xray'].shape)
            #else:
            #    print("we have an empty dictionary right now....")
            socket.send_pyobj(myDict)
