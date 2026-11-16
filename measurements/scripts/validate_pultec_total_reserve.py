"""Зарезервированные дробные joint-настройки. Заморозка, рендер, сверка, оценка."""
import csv
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from measure_pultec_lf_joint_grid import ANALYZER,CPS_NORMALIZED,INPUTS,PLUGIN,RENDERER,ROOT
from probe_pultec_total_relative import CPS,MODEL,OUT,RESERVE,arrays,basis,control_weights,curve,record,save,sha256

DIRECTORY=ROOT/"measurements/renders/pultec_lf/total_relative_v2_reserve"
MANIFEST=DIRECTORY/"manifest.json"


def render(directory=DIRECTORY, settings=RESERVE, model=MODEL):
    manifest_path=directory/"manifest.json"
    with (OUT/"total_relative_train.csv").open() as stream:
        results=list(csv.DictReader(stream))
    if len(results)!=176 or any(r["passed"]!="1" for r in results):
        raise ValueError("Train gate failed")
    source=next(r for r in json.loads(INPUTS.read_text())["files"] if r["sample_rate_hz"]==44100)
    signal=ROOT/source["path"]
    if sha256(signal)!=source["sha256"]:
        raise ValueError("Source digest mismatch")
    directory.mkdir(exist_ok=True)
    manifest=dict(model=sha256(model),source=source,rows=[])
    if manifest_path.exists():
        manifest=json.loads(manifest_path.read_text())
        if manifest["model"]!=sha256(model) or manifest["source"]!=source:
            raise ValueError("Reserve identity changed")
    for c in CPS:
        for b,a in settings:
            wav=directory/f"c{c}-b{b}-a{a}.wav"
            if any(r["wav"]==wav.name and r["sha256"]==sha256(wav) for r in manifest["rows"]):
                continue
            if wav.exists():
                raise FileExistsError(wav)
            subprocess.run([RENDERER,PLUGIN,signal,wav,f"0={CPS_NORMALIZED[c]}",f"1={b/10}",
                            f"2={a/10}","8=0.5","9=0.5","10=0.5","11=0","--require-latency=86"],check=True)
            if json.loads(wav.with_suffix(".json").read_text())["latency_samples_reported"]!=86:
                raise ValueError("Latency gate failed")
            manifest["rows"].append(dict(c=c,b=b,a=a,wav=wav.name,sha256=sha256(wav)))
            manifest_path.write_text(json.dumps(manifest,indent=2))


def assess():
    manifest=json.loads(MANIFEST.read_text())
    signal=ROOT/manifest["source"]["path"]
    if sha256(MODEL)!=manifest["model"] or sha256(signal)!=manifest["source"]["sha256"]:
        raise ValueError("Freeze or signal digest mismatch")
    rows=manifest["rows"]
    if {(r["c"],r["b"],r["a"]) for r in rows}!={(c,b,a) for c in CPS for b,a in RESERVE} or len(rows)!=12:
        raise ValueError("Incomplete reserve")
    for r in rows:
        if sha256(DIRECTORY/r["wav"])!=r["sha256"]:
            raise ValueError("Render digest mismatch")
    poles,tables=arrays(json.loads(MODEL.read_text()))
    logs=[]
    for r in rows:
        c,b,a=r["c"],r["b"],r["a"]
        wav=DIRECTORY/r["wav"]
        csv_path=wav.with_suffix(".csv")
        subprocess.run([sys.executable,ANALYZER,"transfer",signal,wav,wav.with_suffix(".transfer.json"),
                        "--latency","86","--fmin","20","--fmax","18000","--csv",csv_path],check=True,
                       stdout=subprocess.DEVNULL)
        f,h,_=curve(csv_path)
        w=sum(wb*wa*tables[CPS.index(c),ib,ia] for ib,wb in control_weights(b,True)
              for ia,wa in control_weights(a,True))
        logs.append(record(c,b,a,f,basis(f,poles)@w,h))
    save("total_relative_reserve.csv",logs)
    print("reserve",sum(r["passed"] for r in logs),len(logs))


if __name__=="__main__":
    {"render":render,"assess":assess}[sys.argv[1]]()
