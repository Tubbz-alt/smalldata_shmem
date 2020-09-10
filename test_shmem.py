import psana
import numpy as np

import os
import logging 
import requests

import sys
sys.path.append('/reg/g/psdm/sw/tools/smalldata_tools')
from smalldata_tools.SmallDataUtils import defaultDetectors, detData
from smalldata_tools.SmallDataDefaultDetector import epicsDetector
from smalldata_tools.SmallDataDefaultDetector import ipmDetector
from smalldata_tools.SmallDataDefaultDetector import ebeamDetector

hutches=['amo','sxr','xpp','xcs','mfx','cxi','mec']

import socket
hostname=socket.gethostname()
for ihutch in hutches:
    if hostname.find(ihutch)>=0:
        hutch=ihutch
        break
ws_url = "https://pswww.slac.stanford.edu/ws/lgbk"
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
resp = requests.get(ws_url + "/lgbk/ws/activeexperiment_for_instrument_station", {"instrument_name": hutch.upper(), "station": 0})
expname = resp.json().get("value", {}).get("name")
#calib dirs currently not mounted...
#calibdir = '/reg/d/psdm/%s/%s/calib'%(hutch,expname)
#psana.setOption('psana.calib-dir',calibdir)

dsname='shmem=psana.0:stop=no'
print('test shmem DEBUG: ', expname, dsname)
ds = psana.DataSource(dsname)
print('connected...',hutch)
defaultDets = defaultDetectors(hutch)

for nevent,evt in enumerate(ds.events()):
    #if nevent == args.noe : break
    print('shmem read DEBUG: ', nevent)
    #if args.exprun.find('shmem')<0:
    #if nevent%(size-1)!=rank-1: continue # different ranks look at different events
    print 'pass here: ',nevent#, rank, nevent%(size-1)
    defData = detData(defaultDets, evt)

    print('defData:',defData)
