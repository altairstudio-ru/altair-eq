"""Проверка запаса точности фиксированного банка на 32 обучающих опорах v4."""
import json
import sys

import numpy as np

from probe_pultec_control_edges import (
    ANCHORS, CENTERS, CPS, DIRECTORY, FILE, LOCAL, MODEL, OUT, ROOT,
    arrays, base_weights, basis, curve, factor, kernel, record, save, sha256,
)
from probe_pultec_total_relative import AXES, EXT, FLAT, LIMIT, TRAIN, errors, measured_curve, paths


def main():
    folder = DIRECTORY.parent / "edges_v4_anchors"
    manifest = json.loads((folder / "manifest.json").read_text())
    source = manifest["source"]
    signal = ROOT / source["path"]
    poles, tables = arrays(json.loads(MODEL.read_text()))
    edge = json.loads(FILE.read_text())
    local = json.loads(LOCAL.read_text())
    assert sha256(signal) == source["sha256"] and sha256(LOCAL) == manifest["model"]
    assert edge["base_sha256"] == sha256(LOCAL) and local["base_sha256"] == sha256(MODEL)
    rows = manifest["rows"]
    assert len(rows) == 32 and {(r["c"],r["b"],r["a"]) for r in rows} == {
        (c,b,a) for c in CPS for b,a in ANCHORS}
    weights = np.asarray(edge["weights"])
    corrections = np.zeros_like(weights)
    upper = basis(EXT, poles)
    tail = basis(np.linspace(EXT[-1], 22050, 192), poles)
    logs = []
    for row in rows:
        c,b,a = row["c"],row["b"],row["a"]
        i = CPS.index(c)
        wav = folder / row["wav"]
        ext = measured_curve(dict(input=str(signal),output=str(wav),
                                  input_sha256=source["sha256"],output_sha256=row["sha256"]), EXT)[0]
        f,h,_ = curve(wav.with_suffix(".csv"))
        design = basis(f,poles)
        start = base_weights(tables[i], np.asarray(local["delta"])[i], b,a)
        start += factor(b,a) * (kernel([[b,a]]) @ weights[i])[0]
        rel = design / h[:,None]
        residual = 1 - rel @ start
        scale = np.where(f < 100,.20,np.where(f < 1000,.15,.10))
        mag = 20 / np.log(10) / scale
        phase = 180 / np.pi / 2
        importance = np.ones(len(f))
        def metrics(w):
            ratio = upper @ w / ext
            return (max(errors(f,design@w,h)/LIMIT),
                    np.max(abs(20*np.log10(abs(ratio)))),np.max(abs(np.angle(ratio,deg=True))))
        baseline = metrics(start)
        best, chosen = baseline, start
        for _ in range(6):
            matrix = np.vstack([rel.real*(mag*importance)[:,None], rel.imag*(phase*importance)[:,None],
                                100*upper.real,100*upper.imag,100*tail.real,100*tail.imag,.05*np.eye(len(start))])
            rhs = np.r_[residual.real*mag*importance,residual.imag*phase*importance,
                        np.zeros(2*(len(upper)+len(tail))+len(start))]
            candidate = start + np.linalg.lstsq(matrix,rhs,rcond=1e-10)[0]
            score = metrics(candidate)
            # Tight guard on changes of measured extended-band maxima (diagnostic units).
            if score[0]<best[0] and score[1]<=baseline[1]+.01 and score[2]<=baseline[2]+.1:
                best,chosen = score,candidate
            ratio = design@candidate/h
            severity = np.maximum(abs(20*np.log10(abs(ratio)))/scale,abs(np.angle(ratio,deg=True))/2)
            importance *= np.clip((severity/max(severity))**.5*1.6,.8,1.6)
        corrections[i,ANCHORS.index((b,a))] = (chosen-start)/factor(b,a)
        for name,w,score in (("v4",start,baseline),("probe",chosen,best)):
            logs.append(dict(model=name,score=score[0],ext_db=score[1],ext_deg=score[2],
                             **record(c,b,a,f,design@w,h)))
    save("anchor_precision_train.csv",logs)
    updated = weights + np.linalg.solve(kernel(CENTERS)[None,:,:],corrections)
    np.testing.assert_allclose(kernel(CENTERS)@(updated-weights),corrections,atol=1e-9)
    payload = dict(edge, weights=updated.tolist(), parent_sha256=sha256(FILE))
    target = OUT / "anchor_precision_train_v5.json"
    encoded = json.dumps(payload,separators=(",",":"))
    if target.exists():
        assert target.read_text() == encoded
    else:
        with target.open("x") as stream:
            stream.write(encoded)
    for name in ("v4","probe"):
        group = [r for r in logs if r["model"]==name]
        print(name,sum(r["passed"] for r in group),max(r["score"] for r in group),
              max(r["ext_db"] for r in group),max(r["ext_deg"] for r in group))
    print("improved",sum(y["score"]<x["score"] for x,y in zip(logs[::2],logs[1::2])),sha256(target))


def evaluate():
    target = OUT / "anchor_precision_train_v5.json"
    frozen = json.loads(target.read_text())
    assert sha256(FILE) == frozen["parent_sha256"]
    poles,tables = arrays(json.loads(MODEL.read_text()))
    delta = np.asarray(json.loads(LOCAL.read_text())["delta"])
    weights = np.asarray(frozen["weights"])
    files = paths()
    cases = []
    for c in CPS:
        for b,a in np.ndindex(11,11):
            group = "flat" if (b,a)==(0,0) else "axis" if (b,a) in AXES else "train" if (b,a) in TRAIN else "exposed"
            cases.append((group,c,b,a,FLAT if group=="flat" else files[c,b,a]))
    for name in ("edges_v4_anchors","edges_v4_reserve","local_control_train",
                 "local_control_reserve","total_relative_v2_reserve"):
        folder = DIRECTORY.parent / name
        for r in json.loads((folder/"manifest.json").read_text())["rows"]:
            cases.append((name,r["c"],r["b"],r["a"],(folder/r["wav"]).with_suffix(".csv")))
    logs = []
    for group,c,b,a,path in cases:
        f,h,_ = curve(path)
        i = CPS.index(c)
        w = base_weights(tables[i],delta[i],b,a)+factor(b,a)*(kernel([[b,a]])@weights[i])[0]
        logs.append(dict(group=group,**record(c,b,a,f,basis(f,poles)@w,h)))
    save("anchor_precision_frozen_evaluation.csv",logs)
    for group in dict.fromkeys(r["group"] for r in logs):
        subset = [r for r in logs if r["group"]==group]
        print(group,sum(r["passed"] for r in subset),len(subset))
    print("misses",[(r["cps"],r["boost"],r["atten"],r["high"],r["phase"]) for r in logs if not r["passed"]])


if __name__ == "__main__":
    {"fit":main,"evaluate":evaluate}[sys.argv[1]]()
