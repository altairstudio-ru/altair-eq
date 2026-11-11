#!/usr/bin/env python3
"""Cross-validate causal SOS parameter morphing at held-out half-step measurements."""
import csv
import json
from pathlib import Path

import numpy as np
from scipy.interpolate import PchipInterpolator

ROOT = Path(__file__).resolve().parents[2]
BASE_FITS = ROOT / "measurements/results/pultec_lf/stable_sos_six_section_fits_r0999.json"
HALF_FITS = ROOT / "measurements/results/pultec_lf/axis_continuation_fits.json"
QUARTER_FITS = ROOT / "measurements/results/pultec_lf/quarter_node_fits.json"
HALF_MANIFEST = ROOT / "measurements/results/pultec_lf/interpolation_44k1_manifest.json"
FLAT_FIT = ROOT / "measurements/results/pultec_lf/flat_reference_fit.json"
OUT = ROOT / "measurements/results/pultec_lf/quarter_morph_cv.json"
SR = 44100
SECTIONS = 6


def read_curve(path):
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    freq = np.array([float(r["freq_hz"]) for r in rows])
    db = np.array([float(r["magnitude_db"]) for r in rows])
    phase = np.deg2rad([float(r["phase_deg"]) for r in rows])
    return freq, 10 ** (db / 20) * np.exp(1j * phase), db


def to_coefficients(parameters):
    coeff = np.zeros((SECTIONS, 5), dtype=float)
    gain = np.exp(parameters[0])
    for i in range(SECTIONS):
        rp, tp, rz, tz = parameters[1 + 4*i:5 + 4*i]
        scale = gain if i == 0 else 1.0
        coeff[i] = [scale, scale * -2 * rz * np.cos(tz), scale * rz * rz,
                    -2 * rp * np.cos(tp), rp * rp]
    return coeff


def stable(coeff):
    for _, _, _, a1, a2 in coeff:
        if not (abs(a2) < 1 and 1 + a1 + a2 > 0 and 1 - a1 + a2 > 0):
            return False
    return True


def response_from_parameters(parameters, omega):
    q = np.exp(-1j * omega)
    h = np.full(q.shape, np.exp(parameters[0]), dtype=complex)
    for i in range(SECTIONS):
        rp, tp, rz, tz = parameters[1 + 4*i:5 + 4*i]
        h *= (1 - 2*rz*np.cos(tz)*q + rz*rz*q*q) / (1 - 2*rp*np.cos(tp)*q + rp*rp*q*q)
    return h


def response_from_coefficients(coeff, omega):
    q = np.exp(-1j * omega)
    h = np.ones(q.shape, dtype=complex)
    for b0,b1,b2,a1,a2 in coeff:
        h *= (b0+b1*q+b2*q*q)/(1+a1*q+a2*q*q)
    return h


def evaluate(pred, target, db, freq, is_stable=True):
    mag = 20*np.log10(np.maximum(np.abs(pred),1e-12))-db
    phase = np.angle(pred*np.conj(target))*180/np.pi
    bands={}
    for lo,hi in ((20,100),(100,1000),(1000,18000)):
        mask=(freq>=lo)&(freq<hi if hi<18000 else freq<=hi)
        bands[f"{lo}-{hi}"]=float(np.max(np.abs(mag[mask])))
    max_phase=float(np.max(np.abs(phase)))
    passed=bool(is_stable and bands["20-100"]<=.2 and bands["100-1000"]<=.15
                and bands["1000-18000"]<=.1 and max_phase<=2)
    return {"pass":passed,"stable":bool(is_stable),
            "band_max_magnitude_error_db":bands,"max_phase_error_deg":max_phase}


def main():
    nodes={}
    base=json.loads(BASE_FITS.read_text(encoding="utf-8"))["results"]
    for row in base:
        if row["sample_rate_hz"]!=SR: continue
        c=row["configuration"]
        if c["lf_boost_ui"] and not c["lf_atten_ui"]: axis="boost"; value=float(c["lf_boost_ui"])
        elif c["lf_atten_ui"] and not c["lf_boost_ui"]: axis="atten"; value=float(c["lf_atten_ui"])
        else: continue
        nodes.setdefault((c["lf_cps_hz"],axis),{})[value]=row["parameters"]
    half_fits=json.loads(HALF_FITS.read_text(encoding="utf-8"))["results"]
    for row in half_fits:
        nodes.setdefault((row["configuration"]["lf_cps_hz"],row["axis"]),{})[float(row["control_value"])]=row["parameters"]
    quarter_fits=json.loads(QUARTER_FITS.read_text(encoding="utf-8"))["results"]
    for row in quarter_fits:
        nodes.setdefault((row["configuration"]["lf_cps_hz"],row["axis"]),{})[float(row["control_value"])]=row["parameters"]
    flat=json.loads(FLAT_FIT.read_text(encoding="utf-8"))["result"]["parameters"]
    for cps in (20,30,60,100):
        for axis in ("boost","atten"):
            nodes.setdefault((cps,axis),{})[0.0]=flat

    manifest=json.loads(HALF_MANIFEST.read_text(encoding="utf-8"))["rows"]
    results=[]
    for row in manifest.values():
        cps,axis=row["lf_cps_hz"],row["axis"]
        value=float(row[f"lf_{axis}_ui"])
        family=nodes[(cps,axis)]
        xs=np.array(sorted(x for x in family if abs(x-value)>1e-10),dtype=float)
        left=max(x for x in xs if x<value); right=min(x for x in xs if x>value)
        fraction=(value-left)/(right-left)
        left_p,right_p=np.asarray(family[left]),np.asarray(family[right])
        linear_p=(1-fraction)*left_p+fraction*right_p
        left_c,right_c=to_coefficients(left_p),to_coefficients(right_p)
        linear_c=(1-fraction)*left_c+fraction*right_c
        root_stack=np.asarray([family[x] for x in xs])
        coeff_stack=np.asarray([to_coefficients(family[x]).reshape(-1) for x in xs])
        root_pchip=PchipInterpolator(xs,root_stack,axis=0)(value)
        coeff_pchip=PchipInterpolator(xs,coeff_stack,axis=0)(value).reshape(SECTIONS,5)
        freq,target,db=read_curve(ROOT/row["analysis_csv"])
        omega=2*np.pi*freq/SR
        values={
            "linear_roots":evaluate(response_from_parameters(linear_p,omega),target,db,freq),
            "linear_coefficients":evaluate(response_from_coefficients(linear_c,omega),target,db,freq,stable(linear_c)),
            "pchip_roots":evaluate(response_from_parameters(root_pchip,omega),target,db,freq),
            "pchip_coefficients":evaluate(response_from_coefficients(coeff_pchip,omega),target,db,freq,stable(coeff_pchip)),
        }
        results.append({"id":row["id"],"lf_cps_hz":cps,"axis":axis,"value":value,
                        "bracket":[left,right],"methods":values})
    summary={}
    for method in ("linear_roots","linear_coefficients","pchip_roots","pchip_coefficients"):
        rows=[r["methods"][method] for r in results]
        summary[method]={"pass":sum(r["pass"] for r in rows),"total":len(rows),
                         "unstable":sum(not r["stable"] for r in rows),
                         "max_phase_error_deg":max(r["max_phase_error_deg"] for r in rows),
                         "max_band_errors_db":{band:max(r["band_max_magnitude_error_db"][band] for r in rows)
                                                for band in ("20-100","100-1000","1000-18000")}}
    OUT.write_text(json.dumps({"schema":"altair-eq.pultec-lf-quarter-morph-cv/1",
                               "method":"leave-one-out held-out measured half-steps between quarter SOS fits",
                               "sample_rate_hz":SR,"summary":summary,"results":results},indent=2)+"\n",encoding="utf-8")
    print(json.dumps(summary,indent=2))
    print(f"details: {OUT}")

if __name__=="__main__": main()
