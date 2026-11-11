#!/usr/bin/env python3
"""Check whether normalized biquad coefficient morphing predicts held-out integer settings."""
import csv
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
FIT_PATH = ROOT / "measurements/results/pultec_lf/stable_sos_six_section_fits_r0999.json"
CONT_PATH = ROOT / "measurements/results/pultec_lf/axis_continuation_fits.json"
OUT = ROOT / "measurements/results/pultec_lf/sos_coefficient_morph_probe.json"
SECTIONS = 6


def sections(parameters):
    result = []
    gain = np.exp(parameters[0])
    for i in range(SECTIONS):
        rp, tp, rz, tz = parameters[1 + 4*i:5 + 4*i]
        row = np.array([1, -2*rz*np.cos(tz), rz*rz,
                        1, -2*rp*np.cos(tp), rp*rp], dtype=float)
        if i == 0:
            row[:3] *= gain
        result.append(row)
    return np.asarray(result)


def response(coeff, omega):
    q = np.exp(-1j * omega)
    h = np.ones(q.shape, dtype=np.complex128)
    for b0,b1,b2,a0,a1,a2 in coeff:
        h *= (b0+b1*q+b2*q*q)/(a0+a1*q+a2*q*q)
    return h


def curve(path):
    with path.open(newline="", encoding="utf-8") as f:
        rows=list(csv.DictReader(f))
    freq=np.array([float(r["freq_hz"]) for r in rows])
    db=np.array([float(r["magnitude_db"]) for r in rows])
    ph=np.deg2rad([float(r["phase_deg"]) for r in rows])
    return freq,10**(db/20)*np.exp(1j*ph),db


def main():
    fits=json.loads(FIT_PATH.read_text(encoding="utf-8"))["results"]
    base={(r["sample_rate_hz"],r["configuration"]["lf_cps_hz"],r["configuration"]["lf_boost_ui"],r["configuration"]["lf_atten_ui"]):r for r in fits}
    cont=json.loads(CONT_PATH.read_text(encoding="utf-8"))["results"]
    half={(r["sample_rate_hz"],r["configuration"]["lf_cps_hz"],r["axis"],r["control_value"]):r for r in cont}
    out=[]
    for cps in (20,30,60,100):
        for axis in ("boost","atten"):
            for control in range(1,10):
                if axis=="boost":
                    left=half.get((44100,cps,axis,control-.5)); right=half.get((44100,cps,axis,control+.5))
                    held=base.get((44100,cps,control,0))
                    config={"lf_boost_ui":control,"lf_atten_ui":0}
                else:
                    left=half.get((44100,cps,axis,control-.5)); right=half.get((44100,cps,axis,control+.5))
                    held=base.get((44100,cps,0,control))
                    config={"lf_boost_ui":0,"lf_atten_ui":control}
                if not (left and right and held): continue
                coeff=.5*sections(left["parameters"])+.5*sections(right["parameters"])
                freq,target,db=curve(ROOT/held["source"])
                h=response(coeff,2*np.pi*freq/44100)
                mag=20*np.log10(np.abs(h))-db
                phase=np.angle(h*np.conj(target))*180/np.pi
                bands={}
                for lo,hi in ((20,100),(100,1000),(1000,18000)):
                    mask=(freq>=lo)&(freq<hi if hi<18000 else freq<=hi)
                    bands[f"{lo}-{hi}"]=float(np.max(np.abs(mag[mask])))
                passed=bool(bands["20-100"]<=.2 and bands["100-1000"]<=.15 and bands["1000-18000"]<=.1 and np.max(np.abs(phase))<=2)
                out.append({"sample_rate_hz":44100,"lf_cps_hz":cps,"axis":axis,"control":control,**config,
                            "pass":passed,"band_max_magnitude_error_db":bands,"max_phase_error_deg":float(np.max(np.abs(phase)))})
    OUT.write_text(json.dumps({"schema":"altair-eq.pultec-lf-sos-coefficient-morph-probe/1",
                               "method":"linear midpoint interpolation of corresponding normalized SOS coefficients",
                               "results":out},indent=2)+"\n",encoding="utf-8")
    print(f"SOS coefficient morph: {sum(r['pass'] for r in out)}/{len(out)}")
    print(f"max errors: magnitude={max(max(r['band_max_magnitude_error_db'].values()) for r in out):.3f} dB, phase={max(r['max_phase_error_deg'] for r in out):.3f} deg")
    print(f"details: {OUT}")


if __name__=="__main__": main()
