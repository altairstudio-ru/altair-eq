"""Перенос коррекции v4 и v5 при поочерёдном исключении дробной опоры."""
import json
import numpy as np
from probe_pultec_control_edges import (ANCHORS, CENTERS, CPS, DIRECTORY, FILE, LOCAL,
    MODEL, OUT, arrays, base_weights, basis, curve, factor, kernel, record, save, sha256)


def main():
    poles, tables = arrays(json.loads(MODEL.read_text()))
    local = json.loads(LOCAL.read_text())
    edge = json.loads(FILE.read_text())
    precise = json.loads((OUT/"anchor_precision_train_v5.json").read_text())
    assert sha256(FILE) == precise["parent_sha256"] and sha256(LOCAL) == edge["base_sha256"]
    assert sha256(MODEL) == local["base_sha256"]
    matrix = kernel(CENTERS)
    folder = DIRECTORY.parent/"edges_v4_anchors"
    rows = json.loads((folder/"manifest.json").read_text())["rows"]
    assert len(rows)==32 and {(r["c"],r["b"],r["a"]) for r in rows}=={(c,b,a) for c in CPS for b,a in ANCHORS}
    logs, detail = [], []
    for row in rows:
        c,b,a = row["c"],row["b"],row["a"]
        i,j = CPS.index(c),ANCHORS.index((b,a))
        keep = np.arange(len(CENTERS)) != j
        f,h,_ = curve((folder/row["wav"]).with_suffix(".csv"))
        design = basis(f,poles)
        start = base_weights(tables[i],np.asarray(local["delta"])[i],b,a)
        logs.append(dict(model="v3",**record(c,b,a,f,design@start,h)))
        for name,model in (("v4",edge),("v5",precise)):
            # Invert the interpolation step to recover independently fitted node targets.
            retained = matrix[keep] @ np.asarray(model["weights"])[i]
            reduced = np.linalg.solve(matrix[np.ix_(keep,keep)],retained)
            predicted = matrix[j,keep] @ reduced
            w = start + factor(b,a)*predicted
            logs.append(dict(model=name,**record(c,b,a,f,design@w,h)))
            if name == "v5" and (b,a) in ANCHORS[:2]:
                # Effective weights of retained node values in the omitted prediction.
                influence = np.linalg.solve(matrix[np.ix_(keep,keep)].T,matrix[j,keep])
                indices = np.flatnonzero(keep)
                neighbor = 1-j
                n = list(indices).index(neighbor)
                pos = np.flatnonzero((f>=20)&(f<=100))
                db = lambda z: 20*np.log10(abs(z))
                p = design@w
                k = pos[np.argmax(abs(db(p[pos]/h[pos])))]
                contribution = design[k]@(factor(b,a)*influence[n]*retained[n])
                detail.append(dict(cps=c,boost=b,atten=a,hz=f[k],neighbor_boost=ANCHORS[neighbor][0],
                                   neighbor_atten=ANCHORS[neighbor][1],weight=influence[n],
                                   before_db=db((design[k]@start)/h[k]),after_db=db(p[k]/h[k]),
                                   without_neighbor_db=db((p[k]-contribution)/h[k]),
                                   bins_over=int(np.sum(abs(db(p[pos]/h[pos]))>.2))))
    save("edge_low_transfer.csv",detail)
    save("edge_anchor_loo.csv",logs)
    for name in ("v3","v4","v5"):
        group = [r for r in logs if r["model"]==name]
        print(name, [sum(r["passed"] for r in group if r["cps"]==c) for c in CPS],
              [round(max(r[k] for r in group),5) for k in ("low","mid","high","phase")])


if __name__=="__main__":
    main()
