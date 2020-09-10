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

#
# I need two loops: one listens to the clients and appends to the master dict
# the other loop listens for requests and sends data if asked for,
#

# Only make socket and connection once

def runmaster(nClients):
#    global socket
    port = "5001"
    context = zmq.Context()
    socket = context.socket(zmq.REP)
    socket.bind("tcp://*:%s" % port)

    myDict={}
    while nClients > 0:
        # Remove client if the run ended
        md = mpidata()
        md.recv()
        ##ideally, there is a reset option from the bokeh server, but we can make this 
        ##optional & reset on run boundaries instead/in addition.
        ##can be ignored while testing on recorded runs.
        #if publish.get_reset_flag():
        #    myDict={}
        #    publish.clear_reset_flag()
        if md.small.endrun: #what if going from just running to recording?
            #nClients -= 1 #No...
            myDict={}
        else:
            #    print 'DEBUG: master: ', md.n_late, md.nEvts   
            #append the lists in the dictionary we got from the clients to a big master dict.
            for mds in md.small.arrayinfolist:
                if mds.name not in myDict.keys():
                    myDict[mds.name]=getattr(md, mds.name)
                else:
                    myDict[mds.name]=np.append(myDict[mds.name], getattr(md, mds.name), axis=0)

            #md.addarray('evt_ts',np.array(evt_ts))
            evt_ts_str = '%.4f'%(md.send_timeStamp[0] + md.send_timeStamp[1]/1e9)
            #here we will send the dict (or whatever we make this here) to the plots.

            #I don't think this will work: this loop needs to be active....
            while True:
                message = socket.recv()
                print("smallData master received request: ", message)
                socket.send_pyobj(myDict)
