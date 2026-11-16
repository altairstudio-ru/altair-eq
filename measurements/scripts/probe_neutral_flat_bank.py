"""Общая нейтральная ветвь и совместная подгонка отклонений от Flat, 44,1 кГц."""
import csv
import json
import sys
from pathlib import Path

import numpy as np
from scipy.interpolate import RBFInterpolator
from scipy.optimize import linprog

from fit_pultec_lf_extended_guard import EXT, JOINT, MODEL, OUT, TRAIN_KEYS, arrays
from probe_pultec_lf_causal_bank import CPS, FLAT, LIMIT, TRAIN, basis, curve, errors, paths
from validate_pultec_lf_causal_bank_extended_band import SR, load_rows, measured_curve, sha256

FILE = OUT / "neutral_shared_pair_v1.json"
AXES = [(b,0) for b in range(1,11)] + [(0,a) for a in range(1,11)]
TAIL = np.linspace(EXT[-1], SR/2, 257)


def solve(design, target, extension, desired, tail, envelope):
    # Minimax component error relative to the complex target, plus a polygonal gain cap.
    relative = design / target[:,None]
    high = extension / desired[:,None]
    inside = np.vstack([relative.real, -relative.real, relative.imag, -relative.imag,
                        high.real, -high.real, high.imag, -high.imag])
    count = len(target)
    margins = np.repeat([.009,.009,.027,.027],count)
    margins = np.r_[margins,np.repeat([.04,.04,.09,.09],len(desired))]
    rhs = np.r_[np.ones(count),-np.ones(count),np.zeros(2*count),
                np.ones(len(desired)),-np.ones(len(desired)),np.zeros(2*len(desired))]
    directions = np.exp(2j*np.pi*np.arange(12)/12)
    cap = np.vstack([(direction*tail).real for direction in directions])
    A = np.vstack([np.column_stack([inside,-margins]),np.column_stack([cap,np.zeros(len(cap))])])
    result = linprog(np.r_[np.zeros(design.shape[1]),1],A_ub=A,
                     b_ub=np.r_[rhs,np.full(len(cap),envelope*np.cos(np.pi/12))],
                     bounds=[(-50,50)]*design.shape[1]+[(0,None)],method="highs")
    if not result.success:
        raise RuntimeError(result.message)
    return result.x[:-1],result.fun


def fit():
    f,flat,_ = curve(FLAT)
    rows,files = load_rows(),paths()
    external = measured_curve(rows[20,0,0],EXT)[0]
    old,_ = arrays(json.loads(MODEL.read_text()))
    poles = np.r_[old,np.exp(2*np.pi*(-650+20000j)/SR)]
    # A common smooth HF target avoids fitting the low-energy end of the sweep.
    dense = np.unique(np.r_[f,np.linspace(1000,18000,160)])
    neutral_target = np.interp(dense,f,flat.real)+1j*np.interp(dense,f,flat.imag)
    reliable = np.arange(0,len(EXT)-16,4)
    neutral,t = solve(basis(dense,poles),neutral_target,basis(EXT[reliable],poles),
                      external[reliable],basis(TAIL,poles),1.35)
    print("neutral minimax",t,flush=True)
    design,high,tail = (basis(freq,poles) for freq in (f,EXT[reliable],TAIL))
    # Shared linear map for all differential targets, with a penalty on unmeasured gain.
    matrix = np.vstack([design.real,design.imag,high.real,high.imag,
                        .03*tail.real,.03*tail.imag,.0005*np.eye(len(neutral))])
    inverse = np.linalg.pinv(matrix)
    tables = {}
    for c in CPS:
        axis = np.zeros((11,11,len(neutral)))
        residual = []
        for b,a in AXES+TRAIN:
            difference = curve(files[c,b,a])[1]-flat
            measured = measured_curve(rows[c,b,a],EXT)[0][reliable]-external[reliable]
            weights = inverse @ np.r_[difference.real,difference.imag,measured.real,measured.imag,
                                      np.zeros(2*len(tail)+len(neutral))]
            if b and a:
                residual.append(weights-axis[b,0]-axis[0,a])
            else:
                axis[b,a] = weights
        anchors = [(0,0)]+AXES
        interp = RBFInterpolator(TRAIN+anchors,np.vstack([residual,np.zeros((len(anchors),len(neutral)))]),
                                 kernel="cubic")
        grid = neutral + axis[:,0,None]+axis[None,0,:]
        for b,a in np.ndindex(11,11):
            if b and a:
                grid[b,a] += interp([[b,a]])[0]
        tables[str(c)] = grid.tolist()
    with FILE.open("x") as stream:
        json.dump(dict(sample_rate=SR,pole_real=poles.real.tolist(),pole_imag=poles.imag.tolist(),
                       layout="48 FIR, 49 real states, 49 imaginary states",tables=tables),stream)


def audit(model_file=FILE, output_name="neutral_shared_pair_v1_audit.csv"):
    poles,tables = arrays(json.loads(model_file.read_text()))
    rows,files = load_rows(),paths()
    f,flat,_ = curve(FLAT)
    design,high,tail = (basis(freq,poles) for freq in (f,EXT,np.linspace(EXT[-1],SR/2,2049)))
    records=[]
    for c in CPS:
        for b,a in np.ndindex(11,11):
            weights=tables[CPS.index(c),b,a]
            target=curve(files[c,b,a])[1] if b or a else flat
            ext=measured_curve(rows[c,b,a],EXT)[0]
            pred=high@weights
            err=errors(f,design@weights,target)
            group="flat" if not (b or a) else "axis" if not b*a else "train" if (b,a) in TRAIN else "exposed"
            records.append([c,b,a,group,*err,int(all(err<=LIMIT)),max(abs(20*np.log10(abs(pred/ext)))),
                            max(abs(np.angle(pred/ext,deg=True))),20*np.log10(abs(pred).max()),
                            20*np.log10(abs(ext).max()),20*np.log10(abs(tail@weights).max())])
    with (OUT/output_name).open("w",newline="") as stream:
        writer=csv.writer(stream)
        writer.writerow("cps boost atten group low mid high phase pass ext_db ext_deg peak ref tail".split())
        writer.writerows(records)
    print("sha256",sha256(model_file))
    for group in ("flat","axis","train","exposed"):
        v=np.array([r[4:] for r in records if r[3]==group])
        print(group,int(v[:,4].sum()),len(v),"max",v.max(axis=0),"p90",np.percentile(v,90,axis=0))


if __name__=="__main__":
    {"fit":fit,"audit":audit}[sys.argv[1]]()
