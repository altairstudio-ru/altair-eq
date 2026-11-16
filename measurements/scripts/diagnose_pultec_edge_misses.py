"""Показывает ошибки v4 и ближайших измерений на частоте каждого промаха."""
import json

import numpy as np

from probe_pultec_control_edges import (CPS, DIRECTORY, FILE, LOCAL, MODEL, arrays,
    base_weights, basis, curve, factor, kernel, paths, save, sha256)
from probe_pultec_total_relative import record


def main():
    poles, tables = arrays(json.loads(MODEL.read_text()))
    local = json.loads(LOCAL.read_text())
    edge = json.loads(FILE.read_text())
    assert local["base_sha256"] == sha256(MODEL) and edge["base_sha256"] == sha256(LOCAL)
    delta, weights = np.array(local["delta"]), np.array(edge["weights"])
    files = paths()
    for name in ("edges_v4_anchors", "edges_v4_reserve", "local_control_train",
                 "local_control_reserve", "total_relative_v2_reserve"):
        folder = DIRECTORY.parent / name
        for row in json.loads((folder/"manifest.json").read_text())["rows"]:
            files[row["c"],row["b"],row["a"]] = (folder/row["wav"]).with_suffix(".csv")
    logs, spectra, transfers = [], [], []
    for c,b,a,metric in ((30,9,4,"dB"),(100,10,1,"deg"),(100,4.5,4.5,"dB")):
        i = CPS.index(c)
        f,target = curve(files[c,b,a])[:2]
        design = basis(f,poles)
        def predict(x,y):
            w = base_weights(tables[i],delta[i],x,y)
            previous = design @ w
            current = design @ (w+factor(x,y)*(kernel([[x,y]])@weights[i])[0])
            return previous,current
        def readout(z):
            return 20*np.log10(abs(z)) if metric=="dB" else np.angle(z,deg=True)
        _,pred = predict(b,a)
        mask = (f>=1000 if metric=="dB" else f>=20) & (f<=18000)
        err = readout(pred/target)
        j = np.flatnonzero(mask)[abs(err[mask]).argmax()]
        case = f"{c}/{b}/{a}"
        anchor = {(30,9,4): (9.125,4.125), (100,10,1): (10,1.125)}.get((c,b,a))
        if anchor:
            af, measured = curve(files[(c,*anchor)])[:2]
            np.testing.assert_array_equal(af, f)
            _, modeled = predict(*anchor)
            anchor_ratio = modeled / measured
            motion_ratio = (pred / modeled) / (target / measured)
            np.testing.assert_allclose(anchor_ratio * motion_ratio, pred / target)
            for part, ratio in (("anchor",anchor_ratio), ("motion",motion_ratio),
                                ("total",pred / target)):
                transfers.append(dict(case=case,anchor_boost=anchor[0],anchor_atten=anchor[1],
                                      part=part,unit=metric,hz=f[j],signed=readout(ratio[j]),
                                      **record(c,b,a,f,ratio,np.ones_like(ratio))))
        for k in np.flatnonzero(mask):
            spectra.append(dict(case=case,unit=metric,hz=f[k],error=err[k]))
        near = sorted(((x,y) for cc,x,y in files if cc==c and (x,y)!=(b,a)),
                      key=lambda xy:(np.hypot(xy[0]-b,xy[1]-a),xy))[:6]
        for x,y in [(b,a)]+near:
            grid,h = curve(files[c,x,y])[:2]
            assert np.array_equal(grid,f)
            v3,v4 = predict(x,y)
            logs.append(dict(case=case,unit=metric,hz=f[j],boost=x,atten=y,
                             ref=readout(h[j]),model=readout(v4[j]),v3_error=readout(v3[j]/h[j]),
                             v4_error=readout(v4[j]/h[j]),ref_change=readout(h[j]/target[j]),
                             model_change=readout(v4[j]/pred[j])))
        print(case, f[j], err[j], "outside",np.count_nonzero(abs(err[mask])>(.1 if metric=="dB" else 2)))
    save("control_edges_miss_neighbors.csv",logs)
    save("control_edges_miss_spectra.csv",spectra)
    save("control_edges_hf_decomposition.csv",transfers)


if __name__=="__main__":
    main()
