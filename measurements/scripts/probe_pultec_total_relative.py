"""Проверка реконструкции v1 и подгонка полного отклика при фиксированном Flat."""
import csv
import json
import sys

import numpy as np
from scipy.interpolate import RBFInterpolator

from probe_neutral_flat_bank import AXES, CPS, EXT, FILE, FLAT, LIMIT, OUT, TAIL, TRAIN
from probe_neutral_flat_bank import arrays, basis, curve, errors, load_rows, measured_curve, paths, sha256
from check_pultec_lf_local_pair import control_weights

MODEL = OUT / "total_relative_v2.json"
RESERVE = [(1.5,7.5),(4.5,4.5),(8.5,2.5)]


def save(name, records):
    with (OUT/name).open("w",newline="",encoding="utf-8") as stream:
        writer=csv.DictWriter(stream,fieldnames=records[0])
        writer.writeheader()
        writer.writerows(records)


def record(c,b,a,f,p,h):
    v=errors(f,p,h)
    return dict(cps=c,boost=b,atten=a,low=v[0],mid=v[1],high=v[2],phase=v[3],
                passed=int(all(v<=LIMIT)),absolute=max(abs(p-h)))


def before():
    poles,tables=arrays(json.loads(FILE.read_text()))
    files=paths()
    f,flat,_=curve(FLAT)
    d=basis(f,poles)
    logs=[]
    for i,c in enumerate(CPS):
        w=tables[i]
        for b,a in AXES+TRAIN:
            h=curve(files[c,b,a])[1]
            p=d@w[b,a]
            base=w[b,0]+w[0,a]-w[0,0]
            r=record(c,b,a,f,p,h)
            r["sum_identity"]=max(abs(p-(d@base+d@(w[b,a]-base))))
            r["ideal_flat_pass"]=int(all(errors(f,p+flat-d@w[0,0],h)<=LIMIT))
            logs.append(r)
    save("total_relative_before.csv",logs)
    print("before",sum(r["passed"] for r in logs),"ideal flat",sum(r["ideal_flat_pass"] for r in logs),
          "sum identity",max(r["sum_identity"] for r in logs))


def fit():
    old=json.loads(FILE.read_text())
    poles,tables=arrays(old)
    f,flat,_=curve(FLAT)
    files,rows=paths(),load_rows()
    d=basis(f,poles)
    idx=np.arange(0,len(EXT)-16,4)
    high=basis(EXT[idx],poles)
    tail=basis(TAIL,poles)
    logs=[]
    for i,c in enumerate(CPS):
        w=tables[i]
        neutral=w[0,0].copy()
        logs.append(record(c,0,0,f,d@neutral,flat))
        for b,a in AXES+TRAIN:
            h=curve(files[c,b,a])[1]
            ext=measured_curve(rows[c,b,a],EXT)[0][idx]
            start=w[b,a].copy()
            rel=d/h[:,None]
            residual=1-rel@start
            # Penalize movement of the v1 tail. Fit relative complex error of the sum.
            freq_weight=np.ones(len(f))
            best=np.inf
            for iteration in range(8):
                weighted=freq_weight[:,None]*rel
                M=np.vstack([weighted.real,.4*weighted.imag,.04*high.real,.04*high.imag,
                             .02*tail.real,.02*tail.imag,.00005*np.eye(len(start))])
                high_delta=ext-high@start
                rhs=np.r_[freq_weight*residual.real,.4*freq_weight*residual.imag,
                          .04*high_delta.real,.04*high_delta.imag,np.zeros(2*len(tail)+len(start))]
                candidate=start+np.linalg.lstsq(M,rhs,rcond=None)[0]
                pred=d@candidate
                score=max(errors(f,pred,h)/LIMIT)
                if score<best:
                    w[b,a]=candidate
                    best=score
                ratio=pred/h
                severity=np.maximum(abs(20*np.log10(abs(ratio)))/.035,abs(np.angle(ratio,deg=True))/1.)
                freq_weight*=np.clip(severity**.5,.8,1.8)
            logs.append(record(c,b,a,f,d@w[b,a],h))
        anchors=[(0,0)]+AXES
        residuals=[w[b,a]-w[b,0]-w[0,a]+neutral for b,a in TRAIN]
        interp=RBFInterpolator(TRAIN+anchors,np.vstack([residuals,np.zeros((len(anchors),len(neutral)))]),kernel="cubic")
        for b,a in np.ndindex(11,11):
            if b*a and (b,a) not in TRAIN:
                w[b,a]=w[b,0]+w[0,a]-neutral+interp([[b,a]])[0]
        old["tables"][str(c)]=w.tolist()
    save("total_relative_train.csv",logs)
    with MODEL.open("x") as stream:
        json.dump(old,stream,separators=(",",":"))
    print("passes",sum(r["passed"] for r in logs),len(logs),"sha256",sha256(MODEL))


if __name__=="__main__":
    {"before":before,"fit":fit}[sys.argv[1]]()
