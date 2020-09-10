import sys
import zmq
import traceback
import yaml
import time
import socket

import numpy as np

if __name__ == '__main__':
    plotName=None
    if len(sys.argv)<2:
        print('you need to pass the name of the plot!')

    plotName=sys.argv[1]
    setupDict=yaml.load(open('smalldata_plot.yml','r'))
    i0var=setupDict[plotName]['i0var']
    sigvar=setupDict[plotName]['sigvar']
    binWidth=setupDict[plotName]['binWidth']
    binEntries=setupDict[plotName]['binEntries']
    FilterVar=setupDict[plotName]['FilterVar']
    FilterVarMin=setupDict[plotName]['FilterVarMin']
    FilterVarMax=setupDict[plotName]['FilterVarMax']
    
    context = zmq.Context()
    socket = context.socket(zmq.SUB)        
    socket.connect("tcp://%s:%d" %('daq-xpp-mon05', 5000))
    socket.setsockopt(zmq.SUBSCRIBE, b"")

    #if socket.poll(timeout=0):
    nrep=1
    while nrep>0:
        socket.send_string("Request_for test")
        nowStr = time.strftime("%b %d %Y %H:%M:%S", time.localtime())
        print("test requested data at %s "%(nowStr))
        data_dict = socket.recv_pyobj()
        print("got data")

        data={'scanSteps':[]}
        data['scanValues_on']=[]

        scanVarName='delay'
        for key in data_dict.keys():
            if key.find('scan')>=0:
                scanVarName=key
        #no scan, assume it's a delay scan.
        if scanVarName=='delay':
            if np.std(data_dict['enc__lasDelay'])<1e-3:
                print 'no scan, return'
                sys.exit()

        #build the filter variable
        total_filter=np.ones_like(data_dict['lightStatus__xray']).astype(bool)
        filters=[]
        for filterV,fMin,fMax in zip(FilterVar, FilterVarMin, FilterVarMax):
            filters.append(data_dict[filterV]>fMin)
            filters.append(data_dict[filterV]<fMax)
        for ft in filters:
            total_filter&=ft     
        
        #assemble dict for scan plot.
        filtered_data_dict={'sig': data_dict[sigvar]}
        if i0var=='nEntries':
            filtered_data_dict['i0']= np.ones_like(data_dict[sigvar])
        else: 
            filtered_data_dict['i0']= data_dict[i0var]
        filtered_data_dict['laser']= data_dict['lightStatus__laser']
        filtered_data_dict['delay']= data_dict['delay']
        filtered_data_dict[scanVarName]= data_dict[scanVarName]
        
        #apply the filter.
        for key in filtered_data_dict:
            filtered_data_dict[key]=filtered_data_dict[key][total_filter]
        print filtered_data_dict['delay'].shape, scanVarName
        
        #now deal with the binning.
        if scanVarName!='delay' and scanVarName.find('lxt')<0:
            print('default scan')
            scanPoints, scanIdx = np.unique(filtered_data_dict[scanVarName], return_inverse=True)
            scanPointsOff=scanPoints
            scanIdxOn=scanIdx[filtered_data_dict['laser']>0]
            scanIdxOff=scanIdx[filtered_data_dict['laser']==0]
        else:
            print('delay scan', binEntries)
            if binEntries<0:
                print 'here'
                if scanVarName.find('lxt')>=0:
                    scanUnique = np.unique(filtered_data_dict[scanVarName])
                    scanStart=scanUnique[0]
                    scanStop=scanUnique[-1]
                else:
                    scanStart = int(np.nanmin(data_dict['enc__lasDelay'])*10.)/10.
                    scanStop = int(np.nanmax(data_dict['enc__lasDelay'])*10.)/10.
                    print 'enc: ',scanStart, scanStop

                if isinstance(binWidth, int):
                    scanPoints = np.linspace(scanStart,scanStop,binWidth)
                elif isinstance(binWidth, float):
                    scanPoints = np.arange(scanStart,scanStop,binWidth)
                scanIdx = np.digitize(filtered_data_dict['delay'], scanPoints)
                scanPoints = np.concatenate([scanPoints, [scanPoints[-1]+(scanPoints[1]-scanPoints[0])]],0)
                scanPointsOff=scanPoints
                scanIdxOn=scanIdx[filtered_data_dict['laser']>0]
                scanIdxOff=scanIdx[filtered_data_dict['laser']==0]

            else:
                print 'equal size bins'
                #on events
                nEvts=(filtered_data_dict['laser'][filtered_data_dict['laser']>0]).shape[0]
                percentileStepWidth=100./int(nEvts/binEntries)
                percentileSteps=np.arange(0.,100.,percentileStepWidth)
                np.append(percentileSteps,100.)
                print('percentileSteps ',percentileSteps)
                print('midpoint', np.percentile(data_dict['delay'],50))
                scanPoints=np.percentile(data_dict['delay'], percentileSteps)
                scanIdxOn = np.digitize(data_dict['delay'], scanPoints)
                scanPoints = np.concatenate([scanPoints, [scanPoints[-1]+(scanPoints[1]-scanPoints[0])]],0)
                #off events
                nEvts=(filtered_data_dict['laser'][filtered_data_dict['laser']==0]).shape[0]
                percentileStepWidth=100./int(nEvts/binEntries)
                percentileSteps=np.arange(0.,100.,percentileStepWidth)
                np.append(percentileSteps,100.)
                scanPointsOff=np.percentile(data_dict['delay'], percentileSteps)
                scanIdxOff = np.digitize(data_dict['delay'], scanPoints)
                scanPointsOff = np.concatenate([scanPoints, [scanPoints[-1]+(scanPoints[1]-scanPoints[0])]],0)
            
        print 'scanPoints ',scanPoints
        print 'scanPointsOff ',scanPointsOff
        filtered_data_dict_on={}
        filtered_data_dict_off={}
        for key in filtered_data_dict:
            filtered_data_dict_on[key]=filtered_data_dict[key][filtered_data_dict['laser']>0]
            filtered_data_dict_off[key]=filtered_data_dict[key][filtered_data_dict['laser']==0]

        iNorm_on = np.bincount(scanIdxOn, filtered_data_dict_on['i0'], minlength=len(scanPoints)+1)
        iNorm_off = np.bincount(scanIdxOff, filtered_data_dict_off['i0'], minlength=len(scanPointsOff)+1)
        iSig_on = np.bincount(scanIdxOn, filtered_data_dict_on['sig'], minlength=len(scanPoints)+1)
        iSig_off = np.bincount(scanIdxOff, filtered_data_dict_off['sig'], minlength=len(scanPointsOff)+1)

        ratio_on = iSig_on/iNorm_on
        ratio_off = iSig_off/iNorm_off

        print('ratio_on', ratio_on)
        print('ratio_off', ratio_off)
            #for key in self.data.keys():
            #    pdSeriesDict[key]= pd.Series(
            #         data_dict[key][-self.number_of_events:],
            #         index=modTimeData)
            #full_frame = pd.DataFrame(pdSeriesDict)


        print("got data with length %d and: ")
        print(data_dict.keys())
        time.sleep(1)
        nrep-=1

