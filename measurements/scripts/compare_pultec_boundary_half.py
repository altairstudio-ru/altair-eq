"""Сопоставление трёх замороженных моделей на сохранённой контрольной точке."""
import json
import numpy as np
from probe_pultec_control_edges import (CPS, DIRECTORY, FILE, LOCAL, MODEL, OUT, arrays,
    base_weights, basis, curve, factor, kernel, record, save, sha256)


def main():
    folder = DIRECTORY.parent / "boundary_half__7y2162f"
    check = json.loads((folder/"result.json").read_text())
    frozen = OUT/"anchor_precision_train_v5.json"
    v4, v5, local = [json.loads(path.read_text()) for path in (FILE,frozen,LOCAL)]
    assert sha256(folder/"c60-b0.5-a10.wav")==check["wav_sha256"]
    assert sha256(frozen)==check["model_sha256"] and sha256(FILE)==v5["parent_sha256"]
    assert sha256(LOCAL)==v4["base_sha256"]==v5["base_sha256"] and sha256(MODEL)==local["base_sha256"]
    f,h,_ = curve(folder/"transfer.csv")
    poles,tables = arrays(json.loads(MODEL.read_text()))
    i = CPS.index(60)
    start = base_weights(tables[i],np.asarray(local["delta"])[i],.5,10)
    raw = base_weights(tables[i],np.zeros_like(np.asarray(local["delta"])[i]),.5,10)
    weights = [raw,start]+[start+factor(.5,10)*(kernel([[.5,10]])@np.asarray(m["weights"])[i])[0]
                       for m in (v4,v5)]
    predictions = basis(f,poles)@np.asarray(weights).T
    magnitude = 20*np.log10(abs(predictions/h[:,None]))
    phase = np.angle(predictions/h[:,None],deg=True)
    low = np.flatnonzero((f>=20)&(f<=100))
    band = np.flatnonzero((f>=20)&(f<=18000))
    j = low[np.argmax(abs(magnitude[low,-1]))]
    k = band[np.argmax(abs(phase[band,-1]))]
    rows = []
    for n,name in enumerate(("v2 (same interpolation)","v3","v4","v5")):
        result = record(60,.5,10,f,predictions[:,n],h)
        rows.append(dict(model=name,**result,hz_mag=f[j],signed_db=magnitude[j,n],
                         hz_phase=f[k],signed_deg=phase[k,n]))
        print(name,result["low"],result["mid"],result["high"],result["phase"],
              f[j],magnitude[j,n],f[k],phase[k,n])
    for field in ("low","mid","high","phase"):
        np.testing.assert_allclose(rows[-1][field],check[field],atol=1e-10,rtol=0)
    save("boundary_half_versions.csv",rows)


if __name__=="__main__":
    main()
