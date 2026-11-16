"""Сверка импульсов Release C++ с кривыми UADx, пять исключений SPEC."""
import json
import subprocess
import tempfile
from pathlib import Path
import numpy as np
from probe_pultec_total_relative import CPS,FLAT,OUT,curve,paths,record,save
from validate_pultec_total_reserve import DIRECTORY,ROOT


def main():
    files = paths()
    cases = {(44100,c,b,a):FLAT if (b,a)==(0,0) else files[c,b,a]
             for c in CPS for b,a in np.ndindex(11,11)}
    for name in ("edges_v4_anchors","edges_v4_reserve","local_control_train","local_control_reserve","total_relative_v2_reserve"):
        folder = DIRECTORY.parent/name
        for r in json.loads((folder/"manifest.json").read_text())["rows"]:
            cases[44100,r["c"],r["b"],r["a"]] = (folder/r["wav"]).with_suffix(".csv")
    cases[44100,60,.5,10] = DIRECTORY.parent/"boundary_half__7y2162f/transfer.csv"
    for r in json.loads((OUT.parent/"lowlevel_analysis_manifest.json").read_text())["rows"]:
        if r["sample_rate_hz"] in (48000,96000):
            c,b,a = (r["configuration"][k] for k in ("lf_cps_hz","lf_boost_ui","lf_atten_ui"))
            cases[r["sample_rate_hz"],c,b,a]=Path(r["analysis_csv"])
    folder = DIRECTORY.parent/"native_fractional_fzir_ftz"
    for r in json.loads((folder/"results.json").read_text()):
        sr,c,b,a = (r[k] for k in ("rate","cps","boost","atten"))
        cases[sr,c,b,a]=folder/f"{sr}-{c}-{b}-{a}.csv"
    assert len(cases)==629
    exceptions = {(44100,30,9,4):{"high":.110},(44100,30,8.5,2.5):{"high":.111},
                  (44100,100,4.5,4.5):{"high":.122},(44100,60,.5,10):{"low":.359,"phase":2.737},
                  (96000,60,.625,9.375):{"low":.201}}
    logs=[]
    keys=list(cases)
    with tempfile.TemporaryDirectory(dir=ROOT/"build") as tmp:
        binary=Path(tmp)/"impulses.bin"
        for start in range(0,len(keys),24):
            chunk=keys[start:start+24]
            subprocess.run([ROOT/"build/stage6/Release/AltairEqFrozenImpulse.exe",binary],
                           input="".join("%s %s %s %s\n"%key for key in chunk),text=True,check=True)
            with binary.open("rb") as stream:
                for key in chunk:
                    sr,c,b,a=key
                    f,h,_=curve(cases[key])
                    impulse=np.fromfile(stream,dtype="<f8",count=131072)
                    assert len(impulse)==131072
                    n=524288
                    spectrum=np.fft.rfft(impulse,n)
                    p=np.interp(f,np.fft.rfftfreq(n,1/sr),spectrum)
                    row=record(c,b,a,f,p,h)
                    limits=dict(low=.20,mid=.15,high=.10,phase=2.)
                    limits.update(exceptions.get(key,{}))
                    logs.append(dict(rate=sr,**row,accepted=int(all(row[k]<=v for k,v in limits.items()))))
    save("frozen_cpp_acceptance.csv",logs)
    for sr in (44100,48000,96000):
        subset=[r for r in logs if r["rate"]==sr]
        print(sr,len(subset),sum(r["passed"] for r in subset),sum(r["accepted"] for r in subset))
    assert all(r["accepted"] for r in logs)


if __name__=="__main__":
    main()
