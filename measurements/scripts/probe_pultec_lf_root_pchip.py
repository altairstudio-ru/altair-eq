#!/usr/bin/env python3
"""Evaluate PCHIP morphing of sequentially continued SOS roots on held-out integer nodes."""
import csv, json
from pathlib import Path
import numpy as np
from scipy.interpolate import PchipInterpolator

ROOT=Path(__file__).resolve().parents[2]
FITS=ROOT/"measurements/results/pultec_lf/stable_sos_six_section_fits_r0999.json"
CONT=ROOT/"measurements/results/pultec_lf/axis_continuation_fits.json"
OUT=ROOT/"measurements/results/pultec_lf/root_pchip_probe.json"


def read(path):
    with path.open(newline="",encoding="utf-8") as f: rows=list(csv.DictReader(f))
    freq=np.array([float(r["freq_hz"]) for r in rows]); db=np.array([float(r["magnitude_db"]) for r in rows]); phase=np.deg2rad([float(r["phase_deg"]) for r in rows])
    return freq,10**(db/20)*np.exp(1j*phase),db


def response(p,omega):
    q=np.exp(-1j*omega); h=np.full(q.shape,np.exp(p[0]),dtype=complex)
    for i in range(6):
        rp,tp,rz,tz=p[1+4*i:5+4*i]
        h*= (1-2*rz*np.cos(tz)*q+rz*rz*q*q)/(1-2*rp*np.cos(tp)*q+rp*rp*q*q)
    return h


def main():
    base=json.loads(FITS.read_text(encoding="utf-8"))["results"]
    source={(r["sample_rate_hz"],r["configuration"]["lf_cps_hz"],r["configuration"]["lf_boost_ui"],r["configuration"]["lf_atten_ui"]):r for r in base}
    cont=json.loads(CONT.read_text(encoding="utf-8"))["results"]
    by={(r["sample_rate_hz"],r["configuration"]["lf_cps_hz"],r["axis"],r["control_value"]):r for r in cont}
    result=[]
    for cps in (20,30,60,100):
        for axis in ("boost","atten"):
            rows=sorted([r for r in cont if r["sample_rate_hz"]==44100 and r["configuration"]["lf_cps_hz"]==cps and r["axis"]==axis],key=lambda x:x["control_value"])
            x=np.array([r["control_value"] for r in rows]); pars=np.array([r["parameters"] for r in rows])
            # Angles are bounded to [0, pi] by the fitter; preserve that fitted branch.
            interp=PchipInterpolator(x,pars,axis=0)
            for control in range(1,10):
                p=interp(control)
                held=source.get((44100,cps,control,0) if axis=="boost" else (44100,cps,0,control))
                if not held: continue
                freq,target,db=read(ROOT/held["source"]); h=response(p,2*np.pi*freq/44100)
                mag=20*np.log10(np.abs(h))-db; phase=np.angle(h*np.conj(target))*180/np.pi
                bands={}
                for lo,hi in ((20,100),(100,1000),(1000,18000)):
                    m=(freq>=lo)&(freq<hi if hi<18000 else freq<=hi); bands[f"{lo}-{hi}"]=float(np.max(np.abs(mag[m])))
                passed=bool(bands["20-100"]<=.2 and bands["100-1000"]<=.15 and bands["1000-18000"]<=.1 and np.max(np.abs(phase))<=2)
                result.append({"sample_rate_hz":44100,"lf_cps_hz":cps,"axis":axis,"control":control,"pass":passed,"band_max_magnitude_error_db":bands,"max_phase_error_deg":float(np.max(np.abs(phase)))})
    OUT.write_text(json.dumps({"schema":"altair-eq.pultec-lf-root-pchip-probe/1","method":"PCHIP over sequential SOS root fit parameters","results":result},indent=2)+"\n",encoding="utf-8")
    print(f"SOS root PCHIP: {sum(r['pass'] for r in result)}/{len(result)}")
    print(f"max magnitude={max(max(r['band_max_magnitude_error_db'].values()) for r in result):.3f} dB, max phase={max(r['max_phase_error_deg'] for r in result):.3f} deg")
    print(f"details: {OUT}")

if __name__=="__main__": main()
