#!/usr/bin/env python3
"""Test one global scalar on the fitted joint interaction residual."""
import csv,json,sys
from pathlib import Path
import numpy as np
from scipy.interpolate import RBFInterpolator
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'measurements/scripts'))
import plot_pultec_lf_joint_holdout_diagnostics as model
BASE=ROOT/'measurements/results/pultec_lf/lowlevel_analysis_manifest.json';COARSE=ROOT/'measurements/results/pultec_lf/joint_grid_44k1_coarse_manifest.json';INTEGER=ROOT/'measurements/results/pultec_lf/joint_grid_44k1_integer_manifest.json';AXIS=ROOT/'measurements/results/pultec_lf/axis_integer_8sos_fits.json';FLAT_FIT=ROOT/'measurements/results/pultec_lf/flat_reference_fit.json';FLAT=ROOT/'measurements/results/pultec_lf/level_sweep_control_v2/flat-m36-44k1-sweep.csv';FITS=ROOT/'measurements/results/pultec_lf/joint_residual_sos_basis_fits_axisbase_8axis_6sec.json';OUT=ROOT/'measurements/results/pultec_lf/joint_residual_scalar_probe.json';SR=44100
def main():
 targets={}
 for r in json.loads(BASE.read_text(encoding='utf-8'))['rows']:
  if r['sample_rate_hz']!=SR:continue
  c=r['configuration'];k=(c['lf_cps_hz'],float(c['lf_boost_ui']),float(c['lf_atten_ui']));targets[k]=model.curve(ROOT/r['analysis_csv'])
 for m in (COARSE,INTEGER):
  for r in json.loads(m.read_text(encoding='utf-8'))['rows'].values():
   if r.get('status')=='complete':targets[(r['lf_cps_hz'],float(r['lf_boost_ui']),float(r['lf_atten_ui']))]=model.curve(ROOT/r['analysis_csv'])
 axes={}
 for r in json.loads(AXIS.read_text(encoding='utf-8'))['results']:
  c=r['configuration'];axes[(c['lf_cps_hz'],float(c['lf_boost_ui']),float(c['lf_atten_ui']))]=r
 flatp=json.loads(FLAT_FIT.read_text(encoding='utf-8'))['result']['parameters'];ff,flat,_=model.curve(FLAT);rows=json.loads(FITS.read_text(encoding='utf-8'))['results'];by={}
 for r in rows:by.setdefault(int(r['key'][0]),{})[tuple(r['key'])]=r
 samples={}
 for cps,fitrows in by.items():
  coords=[];vals=[]
  for b in range(0,11,2):
   for a in range(0,11,2):
    if (b,a) in ((8,2),(2,8)):continue
    if b==0 or a==0:z=np.ones_like(ff,dtype=complex)
    else:
     it=fitrows[(cps,float(b),float(a))];z=model.response(it['parameters'],ff,it['sections'])
    coords.append([b/2,a/2]);vals.append(np.r_[z.real,z.imag])
  rbf=RBFInterpolator(coords,vals,kernel='cubic',degree=1)
  for (tc,b,a),(f,target,db) in targets.items():
   if tc!=cps or b==0 or a==0:continue
   train=(b%2==0 and a%2==0 and (b,a) not in ((8,2),(2,8)))
   if train:
    it=fitrows[(cps,b,a)];res=model.response(it['parameters'],f,it['sections'])
   else:
    v=rbf([[b/2,a/2]])[0];res=v[:len(f)]+1j*v[len(f):]
   base=(model.response(axes[(cps,b,0.0)]['parameters'],f,8)+model.response(axes[(cps,0.0,a)]['parameters'],f,8)-model.response(flatp,f,6))
   samples.setdefault('train' if train else 'holdout',[]).append((cps,b,a,f,target,db,base,res))
 results=[]
 for alpha in np.round(np.arange(-.5,1.501,.025),3):
  item={'alpha':float(alpha)}
  for group in ('train','holdout'):
   data=samples.get(group,[]);passes=0;byc={};violations={}
   for cps,b,a,f,target,db,base,res in data:
    pred=base+alpha*res;mag=20*np.log10(np.maximum(np.abs(pred),1e-12))-db;ph=np.unwrap(np.angle(pred*np.conj(target)))*180/np.pi
    masks=(("20-100",(f>=20)&(f<100),.2),("100-1000",(f>=100)&(f<1000),.15),("1000-18000",(f>=1000)&(f<=18000),.1))
    ok=True;vv=[]
    for name,mask,tol in masks:
     e=float(np.max(np.abs(mag[mask]))); vv.append((name,e));ok &= e<=tol
    pe=float(np.max(np.abs(ph)));ok &= pe<=2;passes+=ok
    q=byc.setdefault(str(cps),{'pass':0,'count':0});q['pass']+=ok;q['count']+=1
    for name,e in vv:
     qv=violations.setdefault(name,0);violations[name]=qv+(e>{'20-100':.2,'100-1000':.15,'1000-18000':.1}[name])
   item[group]={'pass':passes,'count':len(data),'by_cps':byc,'band_fail_curves':violations}
  results.append(item)
 best=max(results,key=lambda x:x['train']['pass'])
 out={'method':'scale the cubic-interpolated six-section joint residual by one global scalar','selected_by':'maximum training pass count; ties use smallest absolute distance from 1.0','best_training_choice':best,'all_alpha_results':results}
 OUT.write_text(json.dumps(out,indent=2)+'\n',encoding='utf-8');print(json.dumps(best,indent=2));print('all:',OUT)
if __name__=='__main__':main()
