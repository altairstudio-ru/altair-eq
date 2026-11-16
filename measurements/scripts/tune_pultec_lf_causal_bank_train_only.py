#!/usr/bin/env python3
"""Train-only sweep of causal-bank high-frequency guard and ridge weights."""
import argparse,csv,json
from pathlib import Path
import numpy as np
from probe_pultec_lf_causal_bank import (BASE,COARSE,FLAT,INTEGER,ROOT,SR,CPS,TRAIN,
                                         basis,curve,paths)

def make_model(freq,data,flat,guard_weight,ridge):
    centers=np.geomspace(12,21000,48);poles=np.exp((-.32+1j)*2*np.pi*centers/SR)
    design=basis(freq,poles);guard=basis(np.linspace(18500,SR/2,32),poles)
    def project(target):
        relative=design/target[:,None]
        matrix=np.vstack([relative.real,.45*relative.imag,guard_weight*guard.real,
                          guard_weight*guard.imag,ridge*np.eye(design.shape[1])])
        rhs=np.r_[np.ones(len(freq)),np.zeros(len(freq)),np.full(len(guard),guard_weight),
                  np.zeros(len(guard)+design.shape[1])]
        return np.linalg.lstsq(matrix,rhs,rcond=None)[0]
    flatw=project(flat);tables={}
    for cps in CPS:
        boost=[flatw]+[project(data(cps,b,0)) for b in range(1,11)]
        atten=[flatw]+[project(data(cps,0,a)) for a in range(1,11)]
        axes=[(0,a) for a in range(0,11,2)]+[(b,0) for b in range(2,11,2)]
        residual=[project(data(cps,b,a))-boost[b]-atten[a]+flatw for b,a in TRAIN]
        from scipy.interpolate import RBFInterpolator
        interp=RBFInterpolator(TRAIN+axes,np.vstack([residual,np.zeros((len(axes),len(flatw)))]),
                               kernel='cubic',degree=1)
        grid=np.empty((11,11,len(flatw)))
        for b,a in np.ndindex(11,11):
            grid[b,a]=boost[b]+atten[a]-flatw
            if b and a:grid[b,a]+=interp([[b,a]])[0]
        tables[cps]=grid
    return poles,tables

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--guard',type=float,default=.01);ap.add_argument('--ridge',type=float,default=.001);ap.add_argument('--out',type=Path,default=ROOT/'measurements/results/pultec_lf/causal_bank/train_only_tuning.json');ap.add_argument('--validate-holdout',action='store_true');args=ap.parse_args()
    files=paths();freq,flat,_=curve(FLAT)
    def data(c,b,a):
        f,z,_=curve(files[c,b,a])
        if not np.array_equal(freq,f):raise ValueError('frequency grid mismatch')
        return z
    poles,tables=make_model(freq,data,flat,args.guard,args.ridge)
    rows=[];limits=(.20,.15,.10,2.)
    for cps in CPS:
        grid=tables[cps]
        for b,a in TRAIN:
            target=data(cps,b,a);pred=basis(freq,poles)@grid[b,a];ratio=pred/target
            mag=abs(20*np.log10(abs(ratio)));phase=abs(np.angle(ratio,deg=True))
            masks=((freq>=20)&(freq<100),(freq>=100)&(freq<1000),(freq>=1000)&(freq<=18000))
            errs=[float(mag[m].max()) for m in masks]+[float(phase[(freq>=20)&(freq<=18000)].max())]
            rows.append([cps,b,a,*errs,int(all(e<=l for e,l in zip(errs,limits)))])
    hf=np.linspace(18000,22050,257);hf_basis=basis(hf,poles);peaks=[]
    for cps in CPS:
        grid=tables[cps]
        for b,a in np.ndindex(11,11):peaks.append(float((20*np.log10(np.maximum(abs(hf_basis@grid[b,a]),1e-12))).max()))
    args.out.parent.mkdir(parents=True,exist_ok=True)
    with args.out.with_suffix('.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.writer(f);w.writerow(['cps','boost','atten','low_db','mid_db','high_db','phase_deg','pass']);w.writerows(rows)
    summary={'guard_weight':args.guard,'ridge':args.ridge,'training_count':len(rows),
             'train_pass':sum(r[-1] for r in rows),'max_train_errors':[max(r[3+i] for r in rows) for i in range(4)],
             'max_response_18_22k_db_over_integer_table':max(peaks),
             'max_pole_radius':float(max(abs(poles))),
             'note':'Fit uses flat, measured axes, and 92 training joint nodes. Holdout is not opened unless --validate-holdout is explicitly set.'}
    if args.validate_holdout:
        limits=(.20,.15,.10,2.);hold=[]
        for cps in CPS:
            grid=tables[cps]
            for b in range(1,11):
                for a in range(1,11):
                    if (b,a) in TRAIN:continue
                    target=data(cps,b,a);pred=basis(freq,poles)@grid[b,a];ratio=pred/target
                    mag=abs(20*np.log10(abs(ratio)));phase=abs(np.angle(ratio,deg=True))
                    masks=((freq>=20)&(freq<100),(freq>=100)&(freq<1000),(freq>=1000)&(freq<=18000))
                    errs=[float(mag[m].max()) for m in masks]+[float(phase[(freq>=20)&(freq<=18000)].max())]
                    hold.append([cps,b,a,*errs,int(all(e<=l for e,l in zip(errs,limits)))])
        summary['holdout_count']=len(hold);summary['holdout_pass']=sum(r[-1] for r in hold)
        summary['holdout_max_errors']=[max(r[3+i] for r in hold) for i in range(4)]
        with args.out.with_name(args.out.stem+'_holdout.csv').open('w',newline='',encoding='utf-8') as f:
            w=csv.writer(f);w.writerow(['cps','boost','atten','low_db','mid_db','high_db','phase_deg','pass']);w.writerows(hold)
    model_out=args.out.with_name(args.out.stem+'_model.json')
    model_out.write_text(json.dumps({'sample_rate':SR,'layout':'48 FIR taps, real states, imaginary states',
                                     'pole_real':poles.real.tolist(),'pole_imag':poles.imag.tolist(),
                                     'tables':{str(k):v.tolist() for k,v in tables.items()},
                                     'guard_weight':args.guard,'ridge':args.ridge},separators=(',',':')),encoding='utf-8')
    args.out.write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8');print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
