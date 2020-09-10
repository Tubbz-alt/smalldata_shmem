import psana
import numpy as np
import os
import logging
import requests

from mpidata import mpidata 

from smalldata_tools.DetObject import DetObject
from smalldata_tools.SmallDataUtils import defaultDetectors
from smalldata_tools.SmallDataUtils import getUserData
from smalldata_tools.SmallDataUtils import detData
from smalldata_tools.utilities import checkDet, printMsg
from smalldata_tools.SmallDataDefaultDetector import epicsDetector
from smalldata_tools.SmallDataDefaultDetector import ipmDetector
from smalldata_tools.SmallDataDefaultDetector import ebeamDetector

from mpi4py import MPI
comm = MPI.COMM_WORLD
rank = comm.Get_rank()
size = comm.Get_size()

ws_url = "https://pswww.slac.stanford.edu/ws/lgbk"
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def runworker(args):
    if args.exprun.find('shmem')<0:
        #get last run from experiment to extract calib info in DetObject
        dsname = args.exprun+':smd'
        run=int(args.exprun.split('run=')[-1])
        hutch=args.exprun.split(':')[0].replace('exp=','')[0:3]
    else: #shared memory.
        hutches=['amo','sxr','xpp','xcs','mfx','cxi','mec']
        import socket
        hostname=socket.gethostname()
        for ihutch in hutches:
            if hostname.find(ihutch)>=0:
                hutch=ihutch
                break

        resp = requests.get(ws_url + "/lgbk/ws/activeexperiment_for_instrument_station", {"instrument_name": hutch.upper(), "station": 0})
        expname = resp.json().get("value", {}).get("name")
        rundoc = requests.get(ws_url + "/lgbk/" + expname  + "/ws/current_run").json()["value"]
        if not rundoc:
            logger.error("Invalid response from server")
        run = int(rundoc['num'])

        #not for XCS, for CXI: copy calib dir if necessary.
        #calibdir = '/reg/d/psdm/%s/%s/calib'%(hutch,expname)
        #psana.setOption('psana.calib-dir',calibdir)

        if args.exprun=='shmem':
            dsname='shmem=psana.0:stop=no' #was for ls6116
        else:
            dsname=args.dsname

    ds = psana.DataSource(dsname)
    defaultDets = defaultDetectors(hutch)
    print '****',defaultDets
    #snelson: jet tracking - EBeam not ready yet.
    #defaultDets.append(ebeamDetector('EBeam','ebeam'))
    dets=[] #this list is for user data and ill initially not be used.

    jungfrauname='jungfrau4M'
    #ROIs=[ [[0,1], [0,152],[0,1024]], 
    #       [[0,1], [0,318], [508,613]] ]
    #have_jungfrau = checkDet(ds.env(), jungfrauname)
    #jThres=5.
    ##jThres=0.1 #for noise test only!
    #if have_jungfrau:
    #    jungfrau = DetObject(jungfrauname ,ds.env(), int(run), common_mode=0)
    #    for iROI,ROI in enumerate(ROIs):
    #        jungfrau.addROI('ROI_%d'%iROI, ROI)
    #        jungfrau['ROI_%d'%iROI].addProj(axis=-1, thresADU=jThres)
    #    dets.append(jungfrau)

    import time
    time0=time.time()
    timeLastEvt=time0
    #slow down code when playing xtc files to look like real data
    timePerEvent=(1./120.)*(size-1)#time one event should take so that code is running 120 Hz

    sendFrequency=50 #send whenever rank has seen x events
    #took out lightStatus__xray as we only send events that are not dropped now....
    #take out l3E as we make these plots using EPICS
    vars_to_send=['event_time','ipm2_dg2__sum','sc2slit_s',\
                  'lightStatus__laser', 'lightStatus__xray',\
                  'ipm4__sum','ipm5__sum']
#                      'lightStatus__laser','tt__FLTPOS','tt__AMPL','tt__ttCorr','enc__lasDelay']
    #vars_to_send=[]

    masterDict={}
    for nevent,evt in enumerate(ds.events()):
        if nevent == args.noe : break
        if args.exprun.find('shmem')<0:
            if nevent%(size-1)!=rank-1: continue # different ranks look at different events
        #print 'pass here: ',nevent, rank, nevent%(size-1)
        defData = detData(defaultDets, evt)

        ###
        #event selection.
        ###
        #check that all required detectors are ok - this should ensure that we don't need to do any fancy event matching/filling at the cost of losing events.
        #print 'defData: ',defData.keys()
        if 'ipm2' in defData.keys() and defData['damage']['ipm2'] < 1:
            continue
        if 'ipm5' in defData.keys() and defData['damage']['ipm5'] < 1:
            continue            
        if defData['damage']['evr0'] < 1:
            continue

        try:
            if defData['damage']['tt'] < 1:
                continue
        except:
            pass

        try:
            if defData['damage']['enc'] < 1:
                continue
        except:
            pass

        damageDet=1
        for det in dets:
            try:
                if defData['damage'][det._name] < 1:
                    damageDet=0
            except:
                pass
        if damageDet < 1:
            continue

        #loop over defined detectors: if requested, need them not to damage.
        #try:
        #    if defData['damage']['enc'] < 1:
        #        continue
        #except:
        #    pass
        
        #only now bother to deal with detector data to save time. 
        #for now, this will be empty and we will only look at defalt data

        userDict = {}
        for det in dets:
            try:
                #this should be a plain dict. Really.
                det.evt = dropObject()
                det.getData(evt)
                #datMasked = np.ma.masked_array(det.evt.dat.squeeze(), ~(det.mask.astype(bool)))
                #print 'masked array; ',datMasked.sum()
                if det._name=='jungfrau512k':
                    userDict[det._name]={}
                    det.evt.dat[det.evt.dat<jThres]=0
                    datMasked = np.ma.masked_array(det.evt.dat.squeeze(), ~(det.mask.astype(bool)))
                    for iROI,ROI in enumerate(ROIs):
                        userDict[det._name]['ROI_%d'%iROI]=datMasked[ROI[1][0]:ROI[1][1],ROI[2][0]:ROI[2][1]].sum()
                        #print 'debug roi: ',userDict[det._name]['ROI_%d'%iROI]
                #det.processDetector()
                #print 'processed data'
                #userDict[det._name]=getUserData(det)
                #print 'dict: ',userDict[det._name]
            except:
                pass
        
        #here we should append the current dict to a dict that will hold a subset of events.
        for key in defData:
            if isinstance(defData[key], dict):
                for skey in defData[key].keys():
                    if isinstance(defData[key][skey], dict):
                        print 'why do I have this level of dict?', key, skey, defData[key][skey].keys()
                        continue
                    varname_in_masterDict = '%s__%s'%(key, skey)
                    if len(vars_to_send)>0 and varname_in_masterDict not in vars_to_send and varname_in_masterDict.find('scan')<0:
                        continue
                    if varname_in_masterDict.find('scan__varStep')>=0:
                        continue
                    if varname_in_masterDict.find('damage__scan')>=0:
                        continue
                    if varname_in_masterDict not in masterDict.keys():
                        masterDict[varname_in_masterDict] = [defData[key][skey]]
                    else:
                        masterDict[varname_in_masterDict].append(defData[key][skey])
            else:
                if len(vars_to_send)>0 and key not in vars_to_send:
                    continue
                if key not in masterDict.keys():
                    masterDict[key]=[defData[key]]
                else:
                    masterDict[key].append(defData[key])

        for key in userDict:
            if isinstance(userDict[key], dict):
                for skey in userDict[key].keys():
                    if isinstance(userDict[key][skey], dict):
                        print 'why do I have this level of dict?', key, skey, userDict[key][skey].keys()
                        continue
                    varname_in_masterDict = '%s__%s'%(key, skey)
                    #if len(vars_to_send)>0 and varname_in_masterDict not in vars_to_send:
                    #    continue
                    if varname_in_masterDict not in masterDict.keys():
                        masterDict[varname_in_masterDict] = [userDict[key][skey]]
                    else:
                        masterDict[varname_in_masterDict].append(userDict[key][skey])

        ###
        # add event time
        ###
        if 'event_time' not in masterDict.keys():
            masterDict['event_time'] = [evt.get(psana.EventId).time()]
        else:
            masterDict['event_time'].append(evt.get(psana.EventId).time())
        ###
        # add delay
        ###
        try:
            delay=defData['tt__ttCorr'] + defData['enc__lasDelay'] 
        except:
            delay=0.
        if 'delay' not in masterDict.keys():
            masterDict['delay'] = [delay]
        else:
            masterDict['delay'].append(delay)

        #make this run at 120 Hz - slow down if necessary
        # send mpi data object to master when desired
        #not sure how this is supposed to work...
        #print 'send: ', len(masterDict['event_time'])%sendFrequency, len(masterDict['event_time']), sendFrequency
        #print 'masterdict ',nevent, rank, nevent%(size-1), masterDict.keys()
        if len(masterDict['event_time'])%sendFrequency == 0:
            timeNow = time.time()
            if (timeNow - timeLastEvt) < timePerEvent*sendFrequency:
                time.sleep(timePerEvent*sendFrequency-(timeNow - timeLastEvt))
                timeLastEvt=time.time()
            #print 'send data, looked at %d events, total ~ %d, run time %g, in rank %d '%(nevent, nevent*(size-1), (time.time()-time0),rank)
            if rank==1 and nevent>0:
                if args.exprun.find('shmem')<0:
                    print 'send data, looked at %d events/rank, total ~ %d, run time %g, approximate rate %g from rank %d'%(nevent, nevent*(size-1), (time.time()-time0), nevent*(size-1)/(time.time()-time0), rank)
                else:
                    print 'send data, looked at %d events/rank, total ~ %d, run time %g, est. rate %g from rank %d, total est rate %g'%(nevent, nevent*(size-1), (time.time()-time0), nevent/(time.time()-time0), rank, nevent*(size-1)/(time.time()-time0))
            md=mpidata()
            #I think add a list of keys of the data dictionary to the client.
            md.addarray('nEvts',np.array([nevent]))
            md.addarray('send_timeStamp', np.array(evt.get(psana.EventId).time()))
            for key in masterDict.keys():
                md.addarray(key,np.array(masterDict[key]))
            md.send()
            print 'masterDict.keys()', masterDict.keys()

            #now reset the local dictionay/lists.
            masterDict={}

    #should be different for shared memory. R
    try:
        md.endrun()	
        print 'call md.endrun from rank ',rank
    except:
        print 'failed to call md.endrun from rank ',rank
        pass
