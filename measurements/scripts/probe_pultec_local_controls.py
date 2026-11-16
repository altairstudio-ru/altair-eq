"""Локальная добавка к таблице весов в области слабого Boost и сильного Atten."""
import json
import csv
import subprocess
import sys

import numpy as np

from validate_pultec_total_reserve import ANALYZER, DIRECTORY, ROOT, render
from probe_pultec_total_relative import (CPS, MODEL, OUT, arrays, basis, control_weights,
                                        curve, paths, record, save, sha256)

BOOST=[0,1.25,2.25,3.25]
ATTEN=[6,7,9,10]
ANCHORS=[(b,a) for b in BOOST[1:-1] for a in ATTEN[1:-1]]
RESERVE=[(1.375,7.25),(1.75,8),(2.125,8.75)]
LOCAL=OUT/"local_control_v3.json"


def correction(b,a,delta):
    x=np.array([np.interp(b,BOOST,v) for v in np.eye(4)])
    y=np.array([np.interp(a,ATTEN,v) for v in np.eye(4)])
    return np.einsum("i,j,ijk->k",x,y,delta)


def historical():
    poles,tables=arrays(json.loads(MODEL.read_text()))
    delta=np.array(json.loads(LOCAL.read_text())["delta"])
    files=paths()
    logs=[]
    with (OUT/"total_relative_exploratory.csv").open() as stream:
        for row in csv.DictReader(stream):
            c,b,a=[int(row[k]) for k in ("cps","boost","atten")]
            i=CPS.index(c)
            adj=correction(b,a,delta[i])
            passed=int(row["pass"])
            if np.any(adj):
                f,h,_=curve(files[c,b,a])
                passed=record(c,b,a,f,basis(f,poles)@(tables[i,b,a]+adj),h)["passed"]
            logs.append(dict(cps=c,boost=b,atten=a,group=row["group"],base=int(row["pass"]),local=passed))
    save("local_control_integer.csv",logs)
    for group in ("flat","axis","train","exposed"):
        print(group,[sum(r[k] for r in logs if r["group"]==group) for k in ("base","local")])


def run(mode):
    fit=mode in ("render-train","fit")
    directory=DIRECTORY.parent/("local_control_train" if fit else "local_control_reserve")
    settings=ANCHORS if fit else RESERVE
    identity=MODEL if fit else LOCAL
    if mode.startswith("render"):
        return render(directory,settings,identity)
    meta=json.loads((directory/"manifest.json").read_text())
    signal=ROOT/meta["source"]["path"]
    if meta["model"]!=sha256(identity) or sha256(signal)!=meta["source"]["sha256"]:
        raise ValueError("Source or model changed")
    rows=meta["rows"]
    if {(r["c"],r["b"],r["a"]) for r in rows}!={(c,b,a) for c in CPS for b,a in settings}:
        raise ValueError("Incomplete measurement grid")
    for r in rows:
        if sha256(directory/r["wav"])!=r["sha256"]:
            raise ValueError("Render changed")
    poles,tables=arrays(json.loads(MODEL.read_text()))
    if fit:
        delta=np.zeros((4,4,4,tables.shape[-1]))
    else:
        model=json.loads(LOCAL.read_text())
        if model["base_sha256"]!=sha256(MODEL):
            raise ValueError("Base model changed")
        delta=np.asarray(model["delta"])
    logs=[]
    for r in rows:
        c,b,a=r["c"],r["b"],r["a"]
        i=CPS.index(c)
        wav=directory/r["wav"]
        csv_path=wav.with_suffix(".csv")
        subprocess.run([sys.executable,ANALYZER,"transfer",signal,wav,wav.with_suffix(".transfer.json"),
                        "--latency","86","--fmin","20","--fmax","18000","--csv",csv_path],
                       check=True,stdout=subprocess.DEVNULL)
        f,h,_=curve(csv_path)
        design=basis(f,poles)
        w=sum(x*y*tables[i,j,k] for j,x in control_weights(b,True) for k,y in control_weights(a,True))
        if fit:
            # Only LF errors need local repair; discourage changes above 1 kHz, including Nyquist.
            d=design/h[:,None]
            residual=1-d@w
            guard=basis(np.linspace(1000,22050,192),poles)
            matrix=np.vstack([d.real,.45*d.imag,guard.real,guard.imag,.0005*np.eye(len(w))])
            rhs=np.r_[residual.real,.45*residual.imag,np.zeros(2*len(guard)+len(w))]
            delta[i,BOOST.index(b),ATTEN.index(a)]=np.linalg.lstsq(matrix,rhs,rcond=None)[0]
        adjustment=correction(b,a,delta[i])
        for name,weights in (("base",w),("local",w+adjustment)):
            logs.append(dict(model=name,**record(c,b,a,f,design@weights,h)))
    save("local_control_"+mode+".csv",logs)
    if fit:
        with LOCAL.open("x") as stream:
            json.dump(dict(base_sha256=sha256(MODEL),boost=BOOST,atten=ATTEN,delta=delta.tolist()),stream)
    for name in ("base","local"):
        group=[r for r in logs if r["model"]==name]
        print(name,sum(r["passed"] for r in group),len(group),
              [max(r[k] for r in group) for k in ("low","mid","high","phase")])


if __name__=="__main__":
    if sys.argv[1]=="historical":
        historical()
        sys.exit()
    if sys.argv[1] not in ("render-train","fit","render-reserve","assess"):
        raise ValueError("Unknown mode")
    run(sys.argv[1])
