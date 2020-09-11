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
from smalldata_tools.roi_rebin import ROIFunc, spectrumFunc
from smalldata_tools.roi_rebin import projectionFunc, sparsifyFunc
from smalldata_tools.waveformFunc import getCMPeakFunc, templateFitFunc
from smalldata_tools.droplet import dropletFunc
from smalldata_tools.photons import photonFunc
from smalldata_tools.azimuthalBinning import azimuthalBinning

def getAzIntParams():
    ret_dict = {'eBeam': 7.75}
    ret_dict['epix10k2M_center'] = [-673.5,86.6]
    ret_dict['epix10k2M_dis_to_sam'] = 77.
    return ret_dict

def getEpix10k2MROIs():
    #from from image.
    return [ [[2,3], [10,75], [120,190]] ,
             [[5,6], [10,75], [120,190]] ]

def getEpixROIs():
    return [ [59,538,250,675] ]



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
    #snelson: jet tracking - EBeam not ready yet.
    #defaultDets.append(ebeamDetector('EBeam','ebeam'))
    dets=[] #this list is for user data and ill initially not be used.

    epixname = 'epix_2'
    ROI_epix = getEpixROIs()
    have_epix = checkDet(ds.env(), epixname)
    if have_epix:
        epix = DetObject(epixname ,ds.env(), int(run), name=epixname,common_mode=6)
        pjFunc = projectionFunc(axis=-1, thresADU=50., mean=True, name='thresAdu50')
        for iROI,ROI in enumerate(ROI_epix):
            epixROI = ROIFunc(name='ROI_%d'%iROI, ROI=ROI)
            epixROI.addFunc(pjFunc)
            epix.addFunc(epixROI)
    dets.append(epix)

    azIntParams = getAzIntParams()
    ROI_epix10k2M = getEpix10k2MROIs()
    scatterDet = 'epix10k2M'
    haveEpix10k2M = checkDet(ds.env(), scatterDet)
    if haveEpix10k2M:
        epix10k2M = DetObject(scatterDet ,ds.env(), int(run), name=scatterDet, common_mode=0)
        for iROI,ROI in enumerate(ROI_epix10k2M):
            epix10k2M.addFunc(ROIFunc(name='ROI_%d'%iROI, ROI=ROI))

        #epix10k2M.azav_eBeam=azIntParams['eBeam']
        #if azIntParams.has_key('epix10k2M_center'):
        #    #was phiBins=1 & Pplane=0 for first production in first shift.
        #    azintFunc = azimuthalBinning(center=azIntParams['epix10k2M_center'], dis_to_sam=azIntParams['epix10k2M_dis_to_sam'], phiBins=11, Pplane=1)
        #    epix10k2M.addFunc(azintFunc)
        #epix10k2M.storeSum(sumAlgo='calib_img')
        dets.append(epix10k2M)

    import time
    time0=time.time()
    timeLastEvt=time0
    #slow down code when playing xtc files to look like real data
    timePerEvent=(1./120.)*(size-1)#time one event should take so that code is running 120 Hz

    sendFrequency=50 #send whenever rank has seen x events
    #took out lightStatus__xray as we only send events that are not dropped now....
    #take out l3E as we make these plots using EPICS
    #vars_to_send=[]
    vars_to_send=['event_time','ipm2_dg2__sum','sc2slit_s',\
                  'lightStatus__laser', 'lightStatus__xray',\
                  'ipm4__sum','ipm5__sum', 'enc__lasDelay', 'l3t__accept']
#                      'lightStatus__laser','tt__FLTPOS','tt__AMPL','tt__ttCorr','enc__lasDelay']
    #vars_to_send_user=[]
    vars_to_send_user = ['epix_2__ROI_0_thresAdu50_data', 'epix10k2M__ROI_0_sum', 'epix10k2M__ROI_1_sum']

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
                det.getData(evt)
                det.processFuncs()
                userDict[det._name]=getUserData(det)
                #print userDict[det._name]
            except:
                pass

        if len(userDict)!=len(dets):
            print '**** Missing user data. Skipping evt.',len(dets),len(userDict)
            continue
        if len(defData)!=len(defaultDets):
            print '**** Missing default data. Skipping evt.',len(defaultDets),len(defData)
            continue
        
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
                    if len(vars_to_send_user)>0 and varname_in_masterDict not in vars_to_send_user:
                        continue
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
            md.addarray('nEvts_sent',np.array([len(masterDict['event_time'])]))
            md.addarray('send_timeStamp', np.array(evt.get(psana.EventId).time()))
            for key in masterDict.keys():
                md.addarray(key,np.array(masterDict[key]))
                print 'worker: adding %s array of shape %d'%(key, len(masterDict[key]))
            md.send()
            print 'worker: masterDict.keys()', masterDict.keys()

            #now reset the local dictionay/lists.
            masterDict={}

    #should be different for shared memory. R
    try:
        md.endrun()	
        print 'call md.endrun from rank ',rank
    except:
        print 'failed to call md.endrun from rank ',rank
        pass
