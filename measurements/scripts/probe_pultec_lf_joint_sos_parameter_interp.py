#!/usr/bin/env python3
"""Test whether interpolating SOS parameters is better than interpolating responses."""
import csv, json
from pathlib import Path
import numpy as np
from scipy.interpolate import RBFInterpolator
ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/'measurements/results/pultec_lf/lowlevel_analysis_manifest.json'
COARSE=ROOT/'measurements/results/pultec_lf/joint_grid_44k1_coarse_manifest.json'
INTEGER=ROOT/'measurements/results/pultec_lf/joint_grid_44k1_integer_manifest.json'
AXIS=ROOT/'measurements/results/pultec_lf/axis_integer_8sos_fits.json'
FLAT_FIT=ROOT/'measurements/results/pultec_lf/flat_reference_fit.json'
JOINT=ROOT/'measurements/results/pultec_lf/joint_residual_sos_basis_fits_axisbase_8axis_6sec.json'
OUT=ROOT/'measurements/results/pultec_lf/joint_sos_parameter_interp_probe.json'
SR=44100
def curve(p):
 with p.open(newline='',encoding='utf-8') as f:r=list(csv.DictReader(f))
 fr=np.array([float(x['freq_hz']) for x in r]); db=np.array([float(x['magnitude_db']) for x in r]); ph=np.deg2rad([float(x['phase_deg']) for x in r]); return fr,10**(db/20)*np.exp(1j*ph),db
def resp(p,f,n):
 q=np.exp(-1j*2*np.pi*f/SR); h=np.full(q.shape,np.exp(p[0]),complex)
 for i in range(n):
  rp,tp,rz,tz=p[1+4*i:5+4*i]; h*=(1-2*rz*np.cos(tz)*q+rz*rz*q*q)/(1-2*rp*np.cos(tp)*q+rp*rp*q*q)
 return h
def main():
 targets={}; axes={}
 for x in json.loads(BASE.read_text(encoding='utf-8'))['rows']:
  if x['sample_rate_hz']!=SR:continue
  c=x['configuration']; k=(c['lf_cps_hz'],float(c['lf_boost_ui']),float(c['lf_atten_ui'])); (axes if k[1]==0 or k[2]==0 else targets)[k]=curve(ROOT/x['analysis_csv'])
 for m in (COARSE,INTEGER):
  for x in json.loads(m.read_text(encoding='utf-8'))['rows'].values():
   if x.get('status')=='complete':targets[(x['lf_cps_hz'],float(x['lf_boost_ui']),float(x['lf_atten_ui']))]=curve(ROOT/x['analysis_csv'])
 axis={}
 for x in json.loads(AXIS.read_text(encoding='utf-8'))['results']:
  c=x['configuration'];axis[(c['lf_cps_hz'],float(c['lf_boost_ui']),float(c['lf_atten_ui']))]=x
 flat=json.loads(FLAT_FIT.read_text(encoding='utf-8'))['result']['parameters']; fits=json.loads(JOINT.read_text(encoding='utf-8'))['results']; summary={}
 for cps in (20,30,60,100):
  rows=[x for x in fits if x['key'][0]==cps]; coords=[]; vals=[]
  for x in rows:coords.append([x['key'][1]/2,x['key'][2]/2]);vals.append(x['parameters'])
  coords=np.array(coords); vals=np.array(vals); n=6
  # Keep the existing SOS ordering; interpolate each pole/zero parameter surface.
  rbf=RBFInterpolator(coords,vals,kernel='cubic',degree=1)
  fails={"20-100":0,"100-1000":0,"1000-18000":0,"phase":0}; maxes={k:0.0 for k in fails}
  count=0
  for (tc,b,a),(f,target,db) in targets.items():
   if tc!=cps or b==0 or a==0:continue
   if b%2==0 and a%2==0 and (b,a) not in ((8,2),(2,8)):continue
   par=rbf([[b/2,a/2]])[0];par[0]=np.clip(par[0],-20,20)
   for j in range(n):
    o=1+4*j;par[o]=np.clip(par[o],.01,.998999);par[o+1]=np.clip(par[o+1],1e-5,np.pi-1e-5);par[o+2]=np.clip(par[o+2],.01,5);par[o+3]=np.clip(par[o+3],1e-5,np.pi-1e-5)
   omega=2*np.pi*f/SR; base=resp(axis[(cps,b,0.0)]['parameters'],f,8)+resp(axis[(cps,0.0,a)]['parameters'],f,8)-resp(flat,f,6);pred=base*resp(par,f,n)
   err=20*np.log10(np.maximum(abs(pred),1e-12))-db;phase=np.unwrap(np.angle(pred*np.conj(target)))*180/np.pi
   bands=(("20-100",(f>=20)&(f<100),.2),("100-1000",(f>=100)&(f<1000),.15),("1000-18000",(f>=1000)&(f<=18000),.1))
   for name,mask,tol in bands:
    e=float(np.max(abs(err[mask])));maxes[name]=max(maxes[name],e);fails[name]+=e>tol
   pe=float(np.max(abs(phase)));maxes['phase']=max(maxes['phase'],pe);fails['phase']+=pe>2;count+=1
  summary[str(cps)]={"holdout":count,"fails":fails,"max_errors":maxes}
 OUT.write_text(json.dumps({"method":"cubic interpolation of six-section SOS parameters","results":summary},indent=2)+"\n",encoding='utf-8');print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
