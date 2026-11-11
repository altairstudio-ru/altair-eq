#!/usr/bin/env python3
"""Fit a stable SOS approximation to the rank-one complex-log interaction mode."""
import csv
import json
import sys
from pathlib import Path

import numpy as np
from scipy.interpolate import RBFInterpolator

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "measurements/scripts"))
import fit_pultec_lf_joint_residual_basis as fitter

AXIS = ROOT / "measurements/results/pultec_lf/axis_integer_8sos_fits.json"
FLAT_FIT = ROOT / "measurements/results/pultec_lf/flat_reference_fit.json"
OUT = ROOT / "measurements/results/pultec_lf/joint_polar_mode_sos.json"
MODE_SCALE = 0.25


def load_data():
    data = {}
    for row in json.loads(fitter.BASE.read_text(encoding="utf-8"))["rows"]:
        if row["sample_rate_hz"] == fitter.SR:
            c = row["configuration"]
            data[(c["lf_cps_hz"], float(c["lf_boost_ui"]), float(c["lf_atten_ui"]))] = fitter.curve(ROOT / row["analysis_csv"])
    for manifest in (fitter.COARSE, fitter.INTEGER):
        for row in json.loads(manifest.read_text(encoding="utf-8"))["rows"].values():
            if row.get("status") == "complete":
                data[(row["lf_cps_hz"], float(row["lf_boost_ui"]), float(row["lf_atten_ui"]))] = fitter.curve(ROOT / row["analysis_csv"])
    axes = {}
    for row in json.loads(AXIS.read_text(encoding="utf-8"))["results"]:
        c = row["configuration"]
        axes[(c["lf_cps_hz"], float(c["lf_boost_ui"]), float(c["lf_atten_ui"]))] = row
    return data, axes


def main():
    data, axes = load_data()
    flat_params = json.loads(FLAT_FIT.read_text(encoding="utf-8"))["result"]["parameters"]
    output = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {
        "schema": "altair-eq.pultec-lf-joint-polar-mode-sos/1", "mode_scale": MODE_SCALE, "results": {}}
    for cps in (20, 30, 60, 100):
        if str(cps) in output["results"]:
            continue
        nodes, coords, log_rows = [], [], []
        for b in range(2, 11, 2):
            for a in range(2, 11, 2):
                if (b, a) in ((8, 2), (2, 8)):
                    continue
                freq, joint, _ = data[(cps, float(b), float(a))]
                omega = 2*np.pi*freq/fitter.SR
                base = (fitter.response(axes[(cps,float(b),0.0)]["parameters"],omega,8)
                        + fitter.response(axes[(cps,0.0,float(a))]["parameters"],omega,8)
                        - fitter.response(flat_params,omega,6))
                ratio = joint/base
                log_rows.append(np.log(np.maximum(np.abs(ratio),1e-12))+1j*np.unwrap(np.angle(ratio)))
                coords.append([b/2,a/2]); nodes.append((b,a))
        log_rows=np.asarray(log_rows); coords=np.asarray(coords)
        u,s,vh=np.linalg.svd(log_rows,full_matrices=False)
        coeff=u[:,0]*s[0]
        rotation=np.exp(-1j*np.angle(np.sum(coeff**2))/2)
        coeff=coeff*rotation
        mode=vh[0]/rotation
        mode_target=np.exp(MODE_SCALE*mode)
        # Unit-circle target is fit as a stable rational response; its unwrapped log
        # is then used as the interpolated spectral basis.
        best=None
        for sections in (4,6,8):
            fit=fitter.fit_residual(freq,mode_target,sections, cps*700003+sections*13, 3, 1800)
            err=fitter.response(fit["parameters"],2*np.pi*freq/fitter.SR,sections)-mode_target
            fit["mode_max_complex_error"]=float(np.max(np.abs(err)))
            fit["mode_complex_rms_error"]=float(np.sqrt(np.mean(np.abs(err)**2)))
            fit["sections"]=sections
            if best is None or fit["mode_complex_rms_error"]<best["mode_complex_rms_error"]:
                best=fit
        fitted_mode=fitter.response(best["parameters"],2*np.pi*freq/fitter.SR,best["sections"])
        fitted_log=np.log(np.maximum(np.abs(fitted_mode),1e-12))+1j*np.unwrap(np.angle(fitted_mode))
        coefficient_rbf=RBFInterpolator(coords,coeff.real[:,None],kernel="cubic",degree=1)
        train_mag=[]; train_phase=[]
        for idx,(b,a) in enumerate(nodes):
            f,joint,joint_db=data[(cps,float(b),float(a))]
            omega=2*np.pi*f/fitter.SR
            base=(fitter.response(axes[(cps,float(b),0.0)]["parameters"],omega,8)
                  +fitter.response(axes[(cps,0.0,float(a))]["parameters"],omega,8)
                  -fitter.response(flat_params,omega,6))
            c=float(coefficient_rbf([[b/2,a/2]])[0,0])
            pred=base*np.exp((c/MODE_SCALE)*fitted_log)
            train_mag.append(20*np.log10(np.maximum(np.abs(pred),1e-12))-joint_db)
            train_phase.append(np.unwrap(np.angle(pred*np.conj(joint)))*180/np.pi)
        hold_mag=[]; hold_phase=[]; hold_ids=[]
        for (tcps,b,a),(f,joint,joint_db) in data.items():
            if tcps!=cps or b==0 or a==0: continue
            if b%2==0 and a%2==0 and (b,a) not in ((8,2),(2,8)): continue
            c=float(coefficient_rbf([[b/2,a/2]])[0,0])
            omega=2*np.pi*f/fitter.SR
            base=(fitter.response(axes[(cps,b,0.0)]["parameters"],omega,8)
                  +fitter.response(axes[(cps,0.0,a)]["parameters"],omega,8)
                  -fitter.response(flat_params,omega,6))
            pred=base*np.exp((c/MODE_SCALE)*fitted_log)
            hold_mag.append(20*np.log10(np.maximum(np.abs(pred),1e-12))-joint_db)
            hold_phase.append(np.unwrap(np.angle(pred*np.conj(joint)))*180/np.pi)
            hold_ids.append([b,a])
        train_mag,train_phase=np.asarray(train_mag),np.asarray(train_phase)
        hold_mag,hold_phase=np.asarray(hold_mag),np.asarray(hold_phase)
        hi=(freq>=1000)&(freq<=18000); lo=(freq>=20)&(freq<=100); mid=(freq>100)&(freq<1000)
        best.update({"coefficient_imag_rms_over_real_rms":float(np.sqrt(np.mean(coeff.imag**2))/max(np.sqrt(np.mean(coeff.real**2)),1e-12)),
                     "train_count":len(train_mag),"holdout_count":len(hold_mag),"holdout_ids":hold_ids,
                     "train_high_mag_fail":int(np.sum(np.max(np.abs(train_mag[:,hi]),axis=1)>.1)),
                     "holdout_high_mag_fail":int(np.sum(np.max(np.abs(hold_mag[:,hi]),axis=1)>.1)),
                     "holdout_low_mag_fail":int(np.sum(np.max(np.abs(hold_mag[:,lo]),axis=1)>.2)),
                     "holdout_mid_mag_fail":int(np.sum(np.max(np.abs(hold_mag[:,mid]),axis=1)>.15)),
                     "holdout_high_phase_fail":int(np.sum(np.max(np.abs(hold_phase[:,hi]),axis=1)>2)),
                     "holdout_high_mag_max_db":float(np.max(np.abs(hold_mag[:,hi]))),
                     "holdout_high_phase_max_deg":float(np.max(np.abs(hold_phase[:,hi]))),
                     "train_high_mag_max_db":float(np.max(np.abs(train_mag[:,hi]))),
                     "parameters":best["parameters"]})
        output["results"][str(cps)]=best
        OUT.write_text(json.dumps(output,indent=2)+"\n",encoding="utf-8")
        print(cps,{k:v for k,v in best.items() if k not in ("parameters","holdout_ids")},flush=True)
    print(f"output: {OUT}")


if __name__=="__main__":
    main()
