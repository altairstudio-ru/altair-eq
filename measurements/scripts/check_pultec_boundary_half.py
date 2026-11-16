"""Независимая проверка замороженной v5 при CPS 60, Boost 0,5 и Atten 10."""
import json
import subprocess
import sys
from pathlib import Path
from tempfile import mkdtemp
import numpy as np
from measure_pultec_lf_joint_grid import ANALYZER, CPS_NORMALIZED, PLUGIN, RENDERER, ROOT
from probe_pultec_control_edges import (CPS, DIRECTORY, FILE, LOCAL, MODEL, OUT, arrays,
    base_weights, basis, curve, factor, kernel, record, sha256)


def main():
    frozen = OUT/"anchor_precision_train_v5.json"
    digest = sha256(frozen)
    assert digest == "db0f980cf439e5044f6b9db758440760e9a7a6a20d95ddddf8d5dac8ac713ac3"
    model = json.loads(frozen.read_text())
    local = json.loads(LOCAL.read_text())
    assert sha256(FILE)==model["parent_sha256"] and sha256(LOCAL)==model["base_sha256"]
    assert sha256(MODEL)==local["base_sha256"]
    source = json.loads((DIRECTORY.parent/"edges_v4_anchors/manifest.json").read_text())["source"]
    signal = ROOT/source["path"]
    assert sha256(signal)==source["sha256"]
    folder = Path(mkdtemp(prefix="boundary_half_",dir=DIRECTORY.parent))
    wav = folder/"c60-b0.5-a10.wav"
    subprocess.run([RENDERER,PLUGIN,signal,wav,f"0={CPS_NORMALIZED[60]}","1=0.05","2=1",
                    "8=0.5","9=0.5","10=0.5","11=0","--require-latency=86"],check=True)
    assert json.loads(wav.with_suffix(".json").read_text())["latency_samples_reported"]==86
    subprocess.run([sys.executable,ANALYZER,"transfer",signal,wav,folder/"transfer.json",
                    "--latency","86","--fmin","20","--fmax","18000","--csv",folder/"transfer.csv"],
                   stdout=subprocess.DEVNULL,check=True)
    f,h,_ = curve(folder/"transfer.csv")
    poles,tables = arrays(json.loads(MODEL.read_text()))
    i = CPS.index(60)
    w = base_weights(tables[i],np.asarray(local["delta"])[i],.5,10)
    w += factor(.5,10)*(kernel([[.5,10]])@np.asarray(model["weights"])[i])[0]
    pred = basis(f,poles)@w
    err = 20*np.log10(abs(pred/h))
    band = np.flatnonzero((f>=20)&(f<=100))
    j = band[np.argmax(abs(err[band]))]
    k = np.argmin(abs(f-36.36))
    result = dict(**record(60,.5,10,f,pred,h),low_hz=f[j],signed_low_db=err[j],
                  probe_hz=f[k],probe_error_db=err[k],model_sha256=digest,
                  source_sha256=source["sha256"],wav_sha256=sha256(wav))
    (folder/"result.json").write_text(json.dumps(result,indent=2))
    print(folder,result)


if __name__=="__main__":
    main()
