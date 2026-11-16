"""Измеренный и расчётный ход Boost при Atten 10 на последовательных интервалах."""
import json
import numpy as np
from probe_pultec_control_edges import (CPS, DIRECTORY, FILE, LOCAL, MODEL, OUT,
    arrays, base_weights, basis, curve, factor, kernel, paths, save, sha256)


def main():
    files = paths()
    for name in ("edges_v4_anchors", "edges_v4_reserve"):
        directory = DIRECTORY.parent/name
        for row in json.loads((directory/"manifest.json").read_text())["rows"]:
            if row["a"] == 10:
                files[row["c"],row["b"],10] = (directory/row["wav"]).with_suffix(".csv")
    local = json.loads(LOCAL.read_text())
    poles,tables = arrays(json.loads(MODEL.read_text()))
    model = json.loads((OUT/"anchor_precision_train_v5.json").read_text())
    assert model["parent_sha256"] == sha256(FILE) and model["base_sha256"] == sha256(LOCAL)
    assert local["base_sha256"] == sha256(MODEL)
    weights,delta = np.asarray(model["weights"]),np.asarray(local["delta"])
    rows = []
    for i,c in enumerate(CPS):
        previous = None
        for b in sorted(b for cc,b,a in files if cc==c and a==10):
            f,h,_ = curve(files[c,b,10])
            w = base_weights(tables[i],delta[i],b,10)+factor(b,10)*(kernel([[b,10]])@weights[i])[0]
            p = basis(f,poles)@w
            if previous is not None:
                left,grid,ref,pred = previous
                np.testing.assert_array_equal(grid,f)
                actual = 20*np.log10(abs(h/ref))
                estimated = 20*np.log10(abs(p/pred))
                error = estimated-actual
                band = np.flatnonzero((f>=20)&(f<=100))
                j = band[np.argmax(abs(error[band]))]
                k = np.flatnonzero(f==20).item()
                rows.append(dict(cps=c,left=left,right=b,hz=f[j],delta_error_db=error[j],
                                 ref_20_db=actual[k],model_20_db=estimated[k],
                                 delta_error_20_db=error[k],righthand_error_20_db=20*np.log10(abs(p[k]/h[k]))))
            previous = b,f,h,p
    save("boost_boundary_steps.csv",rows)
    for c in CPS:
        group = [r for r in rows if r["cps"]==c]
        print(max(group,key=lambda r:abs(r["delta_error_db"])))
    print([r for r in rows if r["cps"]==100 and r["right"]<=2])


if __name__=="__main__":
    main()
