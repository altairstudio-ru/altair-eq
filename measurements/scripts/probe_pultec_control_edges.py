"""Две локальные поправки поверх v3, фиксированные опоры и свежий резерв."""
import csv
import json
import subprocess
import sys

import numpy as np
from scipy.spatial.distance import cdist

from probe_pultec_local_controls import (ANALYZER, CPS, DIRECTORY, LOCAL, MODEL, OUT, ROOT,
    arrays, basis, control_weights, correction, curve, paths, record, render, save, sha256)
from probe_pultec_total_relative import TRAIN, AXES

ANCHORS=[(1.125,10),(.875,9.625),(8.125,1.125),(8.25,3.25),(9.125,3.125),
         (9.125,4.125),(9.125,6.125),(10,1.125)]
RESERVE=[(.875,10),(1.25,9.75),(8.375,1.375),(8.75,3.375),(9.375,4.25),(9.75,1.375)]
FILE=OUT/"control_edges_v4.json"
CENTERS=ANCHORS+TRAIN+AXES+[(0,0)]


def kernel(points):
    radius=cdist(points,CENTERS)/1.75
    return np.maximum(1-radius,0)**4*(1+4*radius)


def base_weights(table,delta,b,a):
    return (sum(x*y*table[j,k] for j,x in control_weights(b,True)
                for k,y in control_weights(a,True))+correction(b,a,delta))


def factor(b,a):
    return min(b,1)*min(a,1)


def main(mode):
    fitting=mode in ("train-wav","fit")
    settings=ANCHORS if fitting else RESERVE
    directory=DIRECTORY.parent/("edges_v4_anchors" if fitting else "edges_v4_reserve")
    identity=LOCAL if fitting else FILE
    if mode.endswith("-wav"):
        return render(directory,settings,identity)
    poles,tables=arrays(json.loads(MODEL.read_text()))
    v3=json.loads(LOCAL.read_text())
    assert sha256(MODEL)==v3["base_sha256"]
    delta=np.asarray(v3["delta"])
    weights=np.zeros((4,len(CENTERS),tables.shape[-1]))
    if not fitting:
        model=json.loads(FILE.read_text())
        assert model["base_sha256"]==sha256(LOCAL)
        weights=np.asarray(model["weights"])
    if mode=="historical":
        files=paths()
        rows=[]
        for old in csv.DictReader((OUT/"local_control_integer.csv").open()):
            c,b,a=[int(old[k]) for k in ("cps","boost","atten")]
            i=CPS.index(c)
            adj=factor(b,a)*kernel([[b,a]])@weights[i]
            passed=int(old["local"])
            if np.max(abs(adj))>1e-10:
                f,h,_=curve(files[c,b,a])
                w=base_weights(tables[i],delta[i],b,a)+adj[0]
                passed=record(c,b,a,f,basis(f,poles)@w,h)["passed"]
            rows.append(dict(**old,v4=passed))
        save("control_edges_integer.csv",rows)
        print([(g,sum(r["v4"] for r in rows if r["group"]==g)) for g in ("flat","axis","train","exposed")])
        fractions=[]
        for folder in [DIRECTORY,DIRECTORY.parent/"local_control_reserve"]:
            manifest=json.loads((folder/"manifest.json").read_text())
            for r in manifest["rows"]:
                c,b,a=r["c"],r["b"],r["a"]
                i=CPS.index(c)
                f,h,_=curve((folder/r["wav"]).with_suffix(".csv"))
                w=base_weights(tables[i],delta[i],b,a)
                v=w+factor(b,a)*(kernel([[b,a]])@weights[i])[0]
                fractions.append(dict(dataset=folder.name,**record(c,b,a,f,basis(f,poles)@v,h)))
        save("control_edges_previous_fractional.csv",fractions)
        print("previous fractional",sum(r["passed"] for r in fractions),len(fractions))
        return
    meta=json.loads((directory/"manifest.json").read_text())
    signal=ROOT/meta["source"]["path"]
    assert sha256(identity)==meta["model"] and sha256(signal)==meta["source"]["sha256"]
    assert {(r["c"],r["b"],r["a"]) for r in meta["rows"]}=={(c,b,a) for c in CPS for b,a in settings}
    for r in meta["rows"]:
        assert sha256(directory/r["wav"])==r["sha256"]
    logs=[]
    for r in meta["rows"]:
        c,b,a=r["c"],r["b"],r["a"]
        i=CPS.index(c)
        wav=directory/r["wav"]
        path=wav.with_suffix(".csv")
        subprocess.run([sys.executable,ANALYZER,"transfer",signal,wav,wav.with_suffix(".transfer.json"),
                        "--latency","86","--fmin","20","--fmax","18000","--csv",path],check=True,
                       stdout=subprocess.DEVNULL)
        f,h,_=curve(path)
        d=basis(f,poles)
        w=base_weights(tables[i],delta[i],b,a)
        if fitting:
            relative=d/h[:,None]
            residual=1-relative@w
            guard=basis(np.linspace(18000,22050,128),poles)
            matrix=np.vstack([relative.real,.45*relative.imag,guard.real,guard.imag,.0005*np.eye(len(w))])
            rhs=np.r_[residual.real,.45*residual.imag,np.zeros(2*len(guard)+len(w))]
            adj=np.linalg.lstsq(matrix,rhs,rcond=None)[0]
            weights[i,ANCHORS.index((b,a))]=adj/factor(b,a)
        else:
            adj=factor(b,a)*(kernel([[b,a]])@weights[i])[0]
        for name,v in (("v3",w),("v4",w+adj)):
            logs.append(dict(model=name,**record(c,b,a,f,d@v,h)))
    save("control_edges_"+mode+".csv",logs)
    if fitting:
        weights=np.linalg.solve(kernel(CENTERS)[None,:,:],weights)
        with FILE.open("x") as stream:
            json.dump(dict(base_sha256=sha256(LOCAL),centers=CENTERS,radius=1.75,weights=weights.tolist()),stream)
    for name in ("v3","v4"):
        group=[r for r in logs if r["model"]==name]
        print(name,sum(r["passed"] for r in group),len(group))


if __name__=="__main__":
    main(sys.argv[1])
