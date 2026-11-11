#!/usr/bin/env python3
"""Validate a causal SOS-bank approximation to the joint LF interaction residual."""
import json
import sys
from pathlib import Path

import numpy as np
from scipy.interpolate import RBFInterpolator

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "measurements/scripts"))
import fit_pultec_lf_stable_sos as fitter
from probe_pultec_lf_joint_cascade import curve, metric

BASE = ROOT / "measurements/results/pultec_lf/lowlevel_analysis_manifest.json"
COARSE = ROOT / "measurements/results/pultec_lf/joint_grid_44k1_coarse_manifest.json"
INTEGER = ROOT / "measurements/results/pultec_lf/joint_grid_44k1_integer_manifest.json"
FITS = ROOT / "measurements/results/pultec_lf/stable_sos_six_section_fits_r0999.json"
JOINT_FITS = ROOT / "measurements/results/pultec_lf/joint_even_sos_fits_6sec_refined.json"
FLAT_FIT = ROOT / "measurements/results/pultec_lf/flat_reference_fit.json"
OUT = ROOT / "measurements/results/pultec_lf/joint_sos_residual_probe.json"
SR = 44100

OUT = JOINT_FITS.with_name(f"{JOINT_FITS.stem}_residual_probe.json")


def fit_response(parameters, freq):
    parameters = np.asarray(parameters)
    omega = 2 * np.pi * freq / SR
    q = np.exp(-1j * omega)
    h = np.full(q.shape, np.exp(parameters[0]), dtype=np.complex128)
    sections = (len(parameters) - 1) // 4
    for index in range(sections):
        rp, tp, rz, tz = parameters[1 + index * 4: 5 + index * 4]
        denominator = 1 - 2 * rp * np.cos(tp) * q + rp * rp * q * q
        numerator = 1 - 2 * rz * np.cos(tz) * q + rz * rz * q * q
        h *= numerator / denominator
    return h


def main():
    fit_rows = json.loads(FITS.read_text(encoding="utf-8"))["results"]
    axis_fits = {}
    for row in fit_rows:
        if row["sample_rate_hz"] != SR:
            continue
        c = row["configuration"]
        key = (c["lf_cps_hz"], float(c["lf_boost_ui"]), float(c["lf_atten_ui"]))
        axis_fits[key] = row
    flat_parameters = json.loads(FLAT_FIT.read_text(encoding="utf-8"))["result"]["parameters"]
    joint_fit_rows = json.loads(JOINT_FITS.read_text(encoding="utf-8"))["results"]
    joint_fits = {tuple(row["key"]): row for row in joint_fit_rows}

    targets = {}
    for row in json.loads(BASE.read_text(encoding="utf-8"))["rows"]:
        if row["sample_rate_hz"] != SR:
            continue
        c = row["configuration"]
        targets[(c["lf_cps_hz"], float(c["lf_boost_ui"]), float(c["lf_atten_ui"]))] = curve(ROOT / row["analysis_csv"])
    for manifest in (COARSE, INTEGER):
        for row in json.loads(manifest.read_text(encoding="utf-8"))["rows"].values():
            if row.get("status") == "complete":
                targets[(row["lf_cps_hz"], float(row["lf_boost_ui"]),
                         float(row["lf_atten_ui"]))] = curve(ROOT / row["analysis_csv"])
    for cps in (20, 30, 60, 100):
        targets[(cps, 0.0, 0.0)] = curve(ROOT / "measurements/results/pultec_lf/level_sweep_control_v2/flat-m36-44k1-sweep.csv")

    kernels = ("cubic", "multiquadric")
    results = []
    basis_fit_pass = {}
    for cps in (20, 30, 60, 100):
        first_key = (cps, 0.0, 0.0)
        freq = targets[first_key][0]
        flat_h = fit_response(flat_parameters, freq)
        coords, residuals = [], []
        for b in range(0, 11, 2):
            for a in range(0, 11, 2):
                if (b, a) in ((8, 2), (2, 8)):
                    continue
                key = (cps, float(b), float(a))
                if b == 0 or a == 0:
                    residual = np.zeros_like(flat_h)
                else:
                    fit = joint_fits.get(key)
                    if fit is None:
                        raise SystemExit(f"missing joint SOS basis fit: {key}")
                    joint_h = fit_response(fit["parameters"], freq)
                    boost_fit = axis_fits[(cps, float(b), 0.0)]
                    atten_fit = axis_fits[(cps, 0.0, float(a))]
                    residual = (joint_h - fit_response(boost_fit["parameters"], freq)
                                - fit_response(atten_fit["parameters"], freq) + flat_h)
                    basis_fit_pass[str(key)] = bool(fit["pass"])
                coords.append([b / 2.0, a / 2.0])
                residuals.append(residual)
        residuals = np.asarray(residuals)
        values = np.concatenate([residuals.real, residuals.imag], axis=1)
        models = {kernel: RBFInterpolator(np.asarray(coords), values, kernel=kernel,
                                          degree=1, epsilon=1.0)
                  for kernel in kernels}
        for b in range(1, 11):
            for a in range(1, 11):
                if b % 2 == 0 and a % 2 == 0 and (b, a) not in ((8, 2), (2, 8)):
                    continue
                key = (cps, float(b), float(a))
                if key not in targets:
                    continue
                freq, target_h, target_db = targets[key]
                base = (fit_response(axis_fits[(cps, float(b), 0.0)]["parameters"], freq)
                        + fit_response(axis_fits[(cps, 0.0, float(a))]["parameters"], freq)
                        - fit_response(flat_parameters, freq))
                for kernel, model in models.items():
                    correction = model(np.array([[b / 2.0, a / 2.0]]))[0]
                    residual = correction[:len(freq)] + 1j * correction[len(freq):]
                    results.append({"id": f"cps{cps}-b{b:02d}-a{a:02d}", "kernel": kernel,
                                    **metric(base + residual, target_h, target_db, freq)})

    summary = {}
    for kernel in kernels:
        subset = [row for row in results if row["kernel"] == kernel]
        summary[kernel] = {"pass": sum(row["pass"] for row in subset), "total": len(subset),
                           "max_phase_error_deg": max(row["phase_error_deg"] for row in subset),
                           "max_magnitude_error_db": {band: max(row["magnitude_error_db"][band] for row in subset)
                                                       for band in ("20-100", "100-1000", "1000-18000")}}
    payload = {"schema": "altair-eq.pultec-lf-joint-sos-residual-probe/1",
               "method": "RBF-weighted sums of six-section stable SOS basis responses for axis and joint-node residuals",
               "sample_rate_hz": SR, "summary": summary,
               "basis_fit_pass": {"pass": sum(basis_fit_pass.values()), "total": len(basis_fit_pass)},
               "results": results}
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"summary": summary, "basis_fit_pass": payload["basis_fit_pass"]}, indent=2))
    print(f"details: {OUT}")


if __name__ == "__main__":
    main()
