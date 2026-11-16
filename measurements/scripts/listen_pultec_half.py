"""Слепые пары для низкоуровневого режима и ретроспективный пересчёт SPEC."""
import csv
import json
import secrets
import subprocess
import numpy as np
import soundfile as sf
from scipy.signal import lfilter
from check_pultec_boundary_half import (CPS, CPS_NORMALIZED, DIRECTORY, FILE, LOCAL, MODEL,
    OUT, PLUGIN, RENDERER, ROOT, arrays, base_weights, factor, kernel, sha256)


def main(high_band=False):
    rate = 44100
    frozen = OUT/"anchor_precision_train_v5.json"
    model = json.loads(frozen.read_text())
    local = json.loads(LOCAL.read_text())
    assert sha256(frozen)=="db0f980cf439e5044f6b9db758440760e9a7a6a20d95ddddf8d5dac8ac713ac3"
    assert model["parent_sha256"]==sha256(FILE) and model["base_sha256"]==sha256(LOCAL)
    assert local["base_sha256"]==sha256(MODEL)
    poles,tables = arrays(json.loads(MODEL.read_text()))
    c,b,a = (100,4.5,4.5) if high_band else (60,.5,10)
    i = CPS.index(c)
    w = base_weights(tables[i],np.asarray(local["delta"])[i],b,a)
    w += factor(b,a)*(kernel([[b,a]])@np.asarray(model["weights"])[i])[0]
    folder = ROOT/"outputs"/("listening-high-20261115" if high_band else "listening-half-20261115")
    folder.mkdir(exist_ok=False)
    work = folder/"audit"
    work.mkdir()
    with (OUT/"anchor_precision_frozen_evaluation.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    rows.append(json.loads((DIRECTORY.parent/"boundary_half__7y2162f/result.json").read_text()))
    for limits in ((.2,.15,.1,2),(.3,.15,.1,2.5),(.4,.15,.1,3)):
        passed=sum(all(float(r[k])<=v for k,v in zip(("low","mid","high","phase"),limits)) for r in rows)
        print(limits,passed,len(rows),flush=True)
    mix,sr = sf.read(next((ROOT/"eq_reaper_project/Media").glob("02 - *.wav")),start=rate*30,frames=rate*12,always_2d=True)
    assert sr==rate and mix.shape==(rate*12,2) and np.std(mix)>.0001
    t = np.arange(rate*12)/rate
    beat = t%.5
    notes = np.array([36.71,36.71,49,55,41.2,41.2,32.7,49])[(t/.5).astype(int)%8]
    phase = 2*np.pi*notes*beat
    bass = (np.sin(phase)+.35*np.sin(2*phase)+.12*np.sin(3*phase))*np.exp(-5*beat)*np.minimum(beat/.008,1)*np.minimum((.5-beat)/.02,1)
    key = {}
    for label,x in (("bass",np.column_stack([bass,bass])),("mix",mix)):
        if high_band and label=="bass":
            continue
        x[:441]*=np.linspace(0,1,441)[:,None]
        x[-441:]*=np.linspace(1,0,441)[:,None]
        x = np.pad(x*10**(-36/20)/np.max(abs(x)),((rate//2,rate//2),(0,0)))
        src,ref = work/(label+"-input.wav"),work/(label+"-ref.wav")
        sf.write(src,x,rate,subtype="PCM_24")
        x,_ = sf.read(src)
        subprocess.run([RENDERER,PLUGIN,src,ref,f"0={CPS_NORMALIZED[c]}",f"1={b/10}",f"2={a/10}",
                        "8=0.5","9=0.5","10=0.5","11=0","--require-latency=86"],check=True)
        assert json.loads(ref.with_suffix(".json").read_text())["latency_samples_reported"]==86
        y,sr = sf.read(ref,always_2d=True)
        assert sr==rate and y.shape==x.shape
        y = y[86:]
        z = lfilter(w[:48],[1],x,axis=0)
        for j,p in enumerate(poles):
            state=lfilter([1-abs(p)],[1,-p],x,axis=0)
            z+=w[48+j]*state.real+w[48+len(poles)+j]*state.imag
        z=z[:len(y)]
        rms=lambda v:np.sqrt(np.mean(v*v))
        assert np.isfinite(z).all() and min(rms(y),rms(z))>0
        z*=rms(y)/rms(z)
        gain=.8/max(np.max(abs(y)),np.max(abs(z)))
        order=secrets.randbelow(2)
        key[label]="AB"[order]
        for letter,data in zip("AB",(y,z) if order==0 else (z,y)):
            sf.write(folder/f"{label}-{letter}.wav",gain*data,rate,subtype="PCM_24")
    (work/"key.json").write_text(json.dumps(key))


if __name__=="__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--high-band",action="store_true")
    main(parser.parse_args().high_band)
