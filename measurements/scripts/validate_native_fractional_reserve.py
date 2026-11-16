"""Независимый резерв CPS20/60 при 48/96 кГц с фиксацией коэффициентов до рендера."""
import json
import subprocess
import sys
from pathlib import Path
from tempfile import mkdtemp
import numpy as np
from check_v5_rate_targets import native_basis
from measure_pultec_lf_joint_grid import ANALYZER,CPS_NORMALIZED,INPUTS,PLUGIN,RENDERER,ROOT
from probe_pultec_control_edges import CPS,DIRECTORY,LOCAL,MODEL,OUT,arrays,base_weights,curve,factor,kernel,record,sha256


def main():
    rates = (48000,96000)
    cases = [(c,b,a) for c in (20,60) for b,a in ((.625,9.375),(4.375,4.625),(9.375,1.625))]
    model = OUT/"anchor_precision_train_v5.json"
    archive = OUT/"native_rate_projection_v1.npz"
    tails = {r:OUT/f"measured_tail_axis_limited_{r}.npy" for r in rates}
    hashes = {str(p):sha256(p) for p in (model,archive,MODEL,LOCAL,*tails.values())}
    folder = Path(mkdtemp(prefix="native_fractional_",dir=DIRECTORY.parent))
    print(folder,flush=True)
    (folder/"freeze.json").write_text(json.dumps(dict(hashes=hashes,cases=cases,rates=rates),indent=2))
    poles,tables = arrays(json.loads(MODEL.read_text()))
    weights = np.asarray(json.loads(model.read_text())["weights"])
    delta = np.asarray(json.loads(LOCAL.read_text())["delta"])
    bank = np.load(archive)
    logs = []
    for rate in rates:
        src, = [s for s in json.loads(INPUTS.read_text())["files"] if s["sample_rate_hz"]==rate]
        signal = ROOT/src["path"]
        assert sha256(signal)==src["sha256"]
        latency = 86 if rate==48000 else 118
        for c,b,a in cases:
            wav = folder/f"{rate}-{c}-{b}-{a}.wav"
            subprocess.run([RENDERER,PLUGIN,signal,wav,f"0={CPS_NORMALIZED[c]}",f"1={b/10}",
                            f"2={a/10}","8=0.5","9=0.5","10=0.5","11=0",f"--require-latency={latency}"],
                           check=True,stdout=subprocess.DEVNULL)
            assert json.loads(wav.with_suffix(".json").read_text())["latency_samples_reported"]==latency
            subprocess.run([sys.executable,ANALYZER,"transfer",signal,wav,wav.with_suffix(".transfer.json"),
                            "--latency",str(latency),"--fmin","20","--fmax","18000","--csv",wav.with_suffix(".csv")],
                           check=True,stdout=subprocess.DEVNULL)
            f,h,_ = curve(wav.with_suffix(".csv"))
            i = CPS.index(c)
            w = base_weights(tables[i],delta[i],b,a)+factor(b,a)*(kernel([[b,a]])@weights[i])[0]
            design = np.exp(-2j*np.pi*f[:,None]*np.arange(96)/rate)
            p = native_basis(f,poles,rate)@(bank[f"map{rate}"]@w)
            p = p*(design[:,:32]@bank[f"reference_ratio_fir{rate}"])+design@np.load(tails[rate])
            logs.append(dict(rate=rate,**record(c,b,a,f,p,h),wav_sha256=sha256(wav),source_sha256=src["sha256"]))
            (folder/"results.json").write_text(json.dumps(logs,indent=2))
            print(rate,c,b,a,logs[-1]["passed"],flush=True)
    assert all(sha256(Path(p))==v for p,v in hashes.items())


if __name__=="__main__":
    main()
