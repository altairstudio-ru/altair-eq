#!/usr/bin/env python3
"""Validate causal parallel-bank output crossfades between stable fitted SOS nodes."""
import csv
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
FIT = ROOT / "measurements/results/pultec_lf/stable_sos_six_section_fits_r0999.json"
FLAT = ROOT / "measurements/results/pultec_lf/flat_reference_fit.json"
CONT = ROOT / "measurements/results/pultec_lf/axis_continuation_fits.json"
MANIFESTS = [ROOT / f"measurements/results/pultec_lf/{name}" for name in (
    "interpolation_44k1_manifest.json", "interpolation_44k1_quarter_manifest.json",
    "interpolation_44k1_cps_focused_manifest.json", "interpolation_44k1_eighth_manifest.json",
    "interpolation_44k1_sixteenth_manifest.json", "interpolation_44k1_quarter_full_manifest.json")]
OUT = ROOT / "measurements/results/pultec_lf/parallel_bank_blend_probe.json"
SR = 44100


def read_curve(path):
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    freq = np.array([float(r["freq_hz"]) for r in rows])
    db = np.array([float(r["magnitude_db"]) for r in rows])
    phase = np.deg2rad([float(r["phase_deg"]) for r in rows])
    return freq, 10 ** (db / 20) * np.exp(1j * phase), db


def response(parameters, omega):
    q = np.exp(-1j * omega)
    h = np.full(q.shape, np.exp(parameters[0]), dtype=np.complex128)
    for i in range(6):
        rp, tp, rz, tz = parameters[1 + 4*i:5 + 4*i]
        h *= (1 - 2*rz*np.cos(tz)*q + rz*rz*q*q) / (1 - 2*rp*np.cos(tp)*q + rp*rp*q*q)
    return h


def evaluate(pred, target, db, freq):
    mag = 20*np.log10(np.maximum(np.abs(pred),1e-12))-db
    phase = np.angle(pred*np.conj(target))*180/np.pi
    bands={}
    for lo,hi in ((20,100),(100,1000),(1000,18000)):
        mask=(freq>=lo)&(freq<hi if hi<18000 else freq<=hi)
        bands[f"{lo}-{hi}"]=float(np.max(np.abs(mag[mask])))
    max_phase=float(np.max(np.abs(phase)))
    passed=bool(bands["20-100"]<=.2 and bands["100-1000"]<=.15 and bands["1000-18000"]<=.1 and max_phase<=2)
    return {"pass":passed,"band_max_magnitude_error_db":bands,"max_phase_error_deg":max_phase}


def main():
    nodes={}
    fits=json.loads(FIT.read_text(encoding="utf-8"))["results"]
    for row in fits:
        if row["sample_rate_hz"]!=SR: continue
        c=row["configuration"]
        if c["lf_boost_ui"] and not c["lf_atten_ui"]: axis="boost"; value=float(c["lf_boost_ui"])
        elif c["lf_atten_ui"] and not c["lf_boost_ui"]: axis="atten"; value=float(c["lf_atten_ui"])
        else: continue
        nodes.setdefault((c["lf_cps_hz"],axis),{})[value]=row["parameters"]
    flat=json.loads(FLAT.read_text(encoding="utf-8"))["result"]["parameters"]
    for cps in (20,30,60,100):
        for axis in ("boost","atten"):
            nodes.setdefault((cps,axis),{})[0.0]=flat
    cont=json.loads(CONT.read_text(encoding="utf-8"))["results"]
    for row in cont:
        if row["sample_rate_hz"]==SR:
            nodes.setdefault((row["configuration"]["lf_cps_hz"],row["axis"]),{})[float(row["control_value"])]=row["parameters"]

    validation=[]
    for manifest in MANIFESTS:
        data=json.loads(manifest.read_text(encoding="utf-8"))
        for row in data["rows"].values():
            if row["status"]=="complete": validation.append((manifest.name,row))
    results=[]
    for grid,row in validation:
        cps,axis=row["lf_cps_hz"],row["axis"]
        value=float(row[f"lf_{axis}_ui"])
        family=nodes[(cps,axis)]
        xs=sorted(x for x in family if abs(x-value)>1e-10)
        left=max(x for x in xs if x<value); right=min(x for x in xs if x>value)
        freq,target,db=read_curve(ROOT/row["analysis_csv"])
        omega=2*np.pi*freq/SR
        fraction=(value-left)/(right-left)
        hl=response(family[left],omega); hr=response(family[right],omega)
        result=evaluate((1-fraction)*hl+fraction*hr,target,db,freq)
        results.append({"grid":grid,"id":row["id"],"lf_cps_hz":cps,"axis":axis,"value":value,
                        "bracket":[left,right],"fraction":fraction,**result})
    summary={}
    for grid in sorted(set(r["grid"] for r in results)):
        subset=[r for r in results if r["grid"]==grid]
        summary[grid]={"pass":sum(r["pass"] for r in subset),"total":len(subset),
                       "max_phase_error_deg":max(r["max_phase_error_deg"] for r in subset),
                       "max_band_errors_db":{band:max(r["band_max_magnitude_error_db"][band] for r in subset)
                                              for band in ("20-100","100-1000","1000-18000")}}
    OUT.write_text(json.dumps({"schema":"altair-eq.pultec-lf-parallel-bank-blend/1",
                               "method":"linear audio-output/complex-response crossfade between neighboring stable fitted SOS banks",
                               "sample_rate_hz":SR,"summary":summary,"results":results},indent=2)+"\n",encoding="utf-8")
    print(json.dumps(summary,indent=2))
    print(f"details: {OUT}")

if __name__=="__main__": main()
