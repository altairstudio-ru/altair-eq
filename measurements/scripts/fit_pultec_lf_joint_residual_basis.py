#!/usr/bin/env python3
"""Fit stable low-order SOS directly to measured Boost/Atten interaction residuals."""
import argparse
import csv
import json
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "measurements/results/pultec_lf/lowlevel_analysis_manifest.json"
COARSE = ROOT / "measurements/results/pultec_lf/joint_grid_44k1_coarse_manifest.json"
INTEGER = ROOT / "measurements/results/pultec_lf/joint_grid_44k1_integer_manifest.json"
FLAT = ROOT / "measurements/results/pultec_lf/level_sweep_control_v2/flat-m36-44k1-sweep.csv"
AXIS_FITS = ROOT / "measurements/results/pultec_lf/stable_sos_six_section_fits_r0999.json"
FLAT_FIT = ROOT / "measurements/results/pultec_lf/flat_reference_fit.json"
OUT = ROOT / "measurements/results/pultec_lf/joint_residual_sos_basis_fits.json"
SR, MAX_RADIUS = 44100, .999


def curve(path):
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    freq = np.array([float(r["freq_hz"]) for r in rows])
    db = np.array([float(r["magnitude_db"]) for r in rows])
    phase = np.deg2rad([float(r["phase_deg"]) for r in rows])
    return freq, 10 ** (db / 20) * np.exp(1j * phase), db


def response(parameters, omega, sections):
    q = np.exp(-1j * omega)
    h = np.full(q.shape, np.exp(parameters[0]), dtype=np.complex128)
    for index in range(sections):
        rp, tp, rz, tz = parameters[1 + index * 4: 5 + index * 4]
        h *= (1 - 2 * rz * np.cos(tz) * q + rz * rz * q * q) / (1 - 2 * rp * np.cos(tp) * q + rp * rp * q * q)
    return h


def fit_residual(freq, target, sections, seed, starts, max_nfev):
    omega = 2 * np.pi * freq / SR
    scale = float(np.sqrt(np.mean(np.abs(target) ** 2)))
    if scale < 1e-10:
        return {"parameters": [0.0] + [0.9, 0.5, 0.9, 0.5] * sections,
                "normalized_complex_rms": 0.0, "max_abs_error": 0.0,
                "max_pole_radius": .9, "fit_cost": 0.0}
    lower = np.array([-20.0] + [0.01, 1e-5, 0.01, 1e-5] * sections)
    upper = np.array([20.0] + [MAX_RADIUS, np.pi, 5.0, np.pi] * sections)

    def residual(parameters):
        delta = (response(parameters, omega, sections) - target) / scale
        return np.concatenate([delta.real, delta.imag])

    best = None
    centers = np.geomspace(24, SR * .27, sections)
    for start_index in range(starts):
        rng = np.random.default_rng(seed + start_index * 104729 + 20261111)
        values = [float(np.log(max(scale, 1e-10)))]
        for center in centers:
            angle = 2 * np.pi * center / SR
            rp = rng.uniform(.86, .995)
            rz = np.clip(rp + rng.normal(0, .025), .75, 1.2)
            tp = np.clip(angle * rng.uniform(.75, 1.3), 1e-4, np.pi - 1e-4)
            tz = np.clip(angle * rng.uniform(.75, 1.3), 1e-4, np.pi - 1e-4)
            values.extend([rp, tp, rz, tz])
        fit = least_squares(residual, np.clip(values, lower + 1e-8, upper - 1e-8),
                            bounds=(lower, upper), max_nfev=max_nfev, x_scale="jac",
                            ftol=1e-9, xtol=1e-9, gtol=1e-9)
        score = float(np.dot(fit.fun, fit.fun))
        print(f"  start {start_index + 1}/{starts} cost={score:.6g} evals={fit.nfev}", flush=True)
        if best is None or score < best[0]:
            best = score, fit.x
    predicted = response(best[1], omega, sections)
    error = predicted - target
    return {"parameters": best[1].tolist(),
            "normalized_complex_rms": float(np.sqrt(np.mean(np.abs(error) ** 2)) / scale),
            "max_abs_error": float(np.max(np.abs(error))),
            "max_pole_radius": float(max(best[1][1::4])), "fit_cost": best[0]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sections", type=int, default=4)
    parser.add_argument("--starts", type=int, default=2)
    parser.add_argument("--max-nfev", type=int, default=1200)
    parser.add_argument("--cps", type=int, nargs="*", default=[20, 30, 60, 100])
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--fit-axis-baseline", action="store_true",
                        help="define residual against stable SOS fits of both single-axis responses")
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else ROOT / args.output
    data = {}
    for row in json.loads(BASE.read_text(encoding="utf-8"))["rows"]:
        if row["sample_rate_hz"] == SR:
            c = row["configuration"]
            data[(c["lf_cps_hz"], float(c["lf_boost_ui"]), float(c["lf_atten_ui"]))] = curve(ROOT / row["analysis_csv"])
    for manifest in (COARSE, INTEGER):
        for row in json.loads(manifest.read_text(encoding="utf-8"))["rows"].values():
            if row.get("status") == "complete":
                data[(row["lf_cps_hz"], float(row["lf_boost_ui"]), float(row["lf_atten_ui"]))] = curve(ROOT / row["analysis_csv"])
    flat = curve(FLAT)
    axis_fits = {}
    flat_parameters = None
    if args.fit_axis_baseline:
        for row in json.loads(AXIS_FITS.read_text(encoding="utf-8"))["results"]:
            if row["sample_rate_hz"] != SR:
                continue
            c = row["configuration"]
            axis_fits[(c["lf_cps_hz"], float(c["lf_boost_ui"]), float(c["lf_atten_ui"]))] = row
        flat_parameters = json.loads(FLAT_FIT.read_text(encoding="utf-8"))["result"]["parameters"]
    saved = json.loads(output.read_text(encoding="utf-8"))["results"] if output.exists() else []
    fits = {tuple(r["key"]): r for r in saved}
    attempted = 0
    for cps in args.cps:
        for b in range(2, 11, 2):
            for a in range(2, 11, 2):
                if (b, a) in ((8, 2), (2, 8)):
                    continue
                key = (cps, float(b), float(a))
                if key in fits:
                    continue
                freq = data[key][0]
                joint = data[key][1]
                boost = data[(cps, float(b), 0.0)][1]
                atten = data[(cps, 0.0, float(a))][1]
                if args.fit_axis_baseline:
                    boost = response(axis_fits[(cps, float(b), 0.0)]["parameters"],
                                     2 * np.pi * freq / SR, 6)
                    atten = response(axis_fits[(cps, 0.0, float(a))]["parameters"],
                                     2 * np.pi * freq / SR, 6)
                    flat_response = response(flat_parameters, 2 * np.pi * freq / SR, 6)
                else:
                    boost = data[(cps, float(b), 0.0)][1]
                    atten = data[(cps, 0.0, float(a))][1]
                    flat_response = flat[1]
                target = joint - boost - atten + flat_response
                print(f"CPS={cps} Boost={b} Atten={a}; residual RMS={np.sqrt(np.mean(np.abs(target)**2)):.6g}", flush=True)
                fit = fit_residual(freq, target, args.sections,
                                   cps * 100000 + b * 1000 + a * 37,
                                   args.starts, args.max_nfev)
                fit.update({"key": list(key), "sample_rate_hz": SR,
                            "sections": args.sections,
                            "source": "measured_joint - measured_boost_axis - measured_atten_axis + measured_flat"})
                fits[key] = fit
                output.write_text(json.dumps({"schema": "altair-eq.pultec-lf-joint-residual-sos-basis/1",
                                              "fit_settings": {"sections": args.sections, "starts": args.starts,
                                                                "max_nfev": args.max_nfev,
                                                                "axis_baseline": "stable SOS fits" if args.fit_axis_baseline else "measured curves"},
                                              "results": list(fits.values())},
                                             ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                print(f"  normalized complex RMS={fit['normalized_complex_rms']:.5g}; "
                      f"max |error|={fit['max_abs_error']:.5g}", flush=True)
                attempted += 1
                if args.limit and attempted >= args.limit:
                    print(f"paused at configured limit; saved {len(fits)} fits -> {output}")
                    return
    print(f"residual basis fits: {len(fits)} -> {output}")


if __name__ == "__main__":
    main()
