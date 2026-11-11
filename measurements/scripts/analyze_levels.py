#!/usr/bin/env python3
"""Measure steady-state gain, harmonic distortion and two-tone products."""
import json
from pathlib import Path
import numpy as np
from scipy.io import wavfile

ROOT=Path(__file__).resolve().parents[2]
MAN=json.loads((ROOT/'measurements/results/pultec_lf/render_manifest.json').read_text(encoding='utf-8'))

def read(path):
    sr,x=wavfile.read(path)
    if x.ndim!=2 or x.shape[1]!=2: raise ValueError('expected stereo '+str(path))
    return sr,x[:,0].astype(np.float64)

def spectrum(path,expected_sr):
    sr,x=read(path)
    if sr!=expected_sr: raise ValueError('sample rate mismatch')
    # Drop leading/trailing startup and cosine fade. Segment is integer seconds,
    # so 50/100/1000 Hz components fall exactly on FFT bins.
    start=sr; end=min(len(x),sr*9)
    x=x[start:end]; x=x-np.mean(x)
    z=np.fft.rfft(x); amp=2*np.abs(z)/len(x); f=np.fft.rfftfreq(len(x),1/sr)
    return f,amp

def binval(f,a,hz): return float(a[int(np.argmin(abs(f-hz)))])

def main():
    results=[]
    for rid,e in MAN['rows'].items():
        row=e.get('grid_row')
        if not row or row['group']!='level_dependence': continue
        src=ROOT/e['input']; dst=ROOT/e['output']; sr=row['sample_rate_hz']
        f,ain=spectrum(src,sr); _,aout=spectrum(dst,sr)
        signal=row['signal']; level=row['level_dbfs']; params=row['plugin']
        item={'id':rid,'signal':signal,'level_dbfs':level,'sample_rate_hz':sr,'parameters':params,
              'input_sha256':e['input_sha256'],'output_sha256':e['output_sha256']}
        if signal.startswith('sine_'):
            hz=int(signal.split('_')[1]); fundamental=binval(f,aout,hz); infund=binval(f,ain,hz)
            harmonics=[]
            for n in range(2,min(20,int((sr/2)//hz))+1):
                h=binval(f,aout,n*hz)
                if h: harmonics.append({'order':n,'frequency_hz':n*hz,'amplitude':h,
                                        'dBc':20*np.log10(h/fundamental)})
            thd=np.sqrt(sum(h['amplitude']**2 for h in harmonics))/max(fundamental,1e-30)
            item.update({'fundamental_hz':hz,'fundamental_gain_db':20*np.log10(max(fundamental,1e-30)/max(infund,1e-30)),
                         'thd_percent':float(thd*100),'harmonics':harmonics})
        elif signal=='twotone_50_1000':
            fund50=binval(f,aout,50); fund1000=binval(f,aout,1000)
            products=[]
            for hz in (900,950,1050,1100,1950,2000,2050):
                amp=binval(f,aout,hz)
                products.append({'frequency_hz':hz,'amplitude':amp,'dBc_vs_50Hz':20*np.log10(max(amp,1e-30)/max(fund50,1e-30))})
            item.update({'fundamental_50_hz_gain_db':20*np.log10(max(fund50,1e-30)/max(binval(f,ain,50),1e-30)),
                         'fundamental_1000_hz_gain_db':20*np.log10(max(fund1000,1e-30)/max(binval(f,ain,1000),1e-30)),
                         'selected_intermod_products':products})
        results.append(item)
    results.sort(key=lambda x:x['id'])
    out=ROOT/'measurements/results/pultec_lf/level_analysis.json'
    out.write_text(json.dumps({'schema':'altair-eq.pultec-lf-level-analysis/1','method':'FFT of 1 s to 9 s steady section; amplitudes at coherent bins','results':results},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('level analysis: {} jobs -> {}'.format(len(results),out))

if __name__=='__main__':main()
