import sys
import zmq
import yaml
import time
import socket

import numpy as np

if __name__ == '__main__':
    nrep=1e6
    if len(sys.argv)>=2:
        nrep=int(sys.argv[1])

    context = zmq.Context()

    socket = context.socket(zmq.REQ)        
    socket.connect("tcp://%s:%d" %('daq-xpp-mon05', 5000))
    while nrep>0:
        socket.send_string("Request_for test")
        nowStr = time.strftime("%b %d %Y %H:%M:%S", time.localtime())
        print("test requested data at %s "%(nowStr))

        data_dict = socket.recv_pyobj()
        laser = data_dict['lightStatus__laser']

        print("got data with length %d and keys: "%laser.shape)
        print(data_dict.keys())
        time.sleep(1)
        nrep-=1
