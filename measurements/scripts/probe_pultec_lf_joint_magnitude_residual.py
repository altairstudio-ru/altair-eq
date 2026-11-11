#!/usr/bin/env python3
"""Compare magnitude-only and complex interpolation of measured LF interaction."""
import csv
import json
from pathlib import Path

import numpy as np
from scipy.interpolate import RBFInterpolator

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "measurements/results/pultec_lf/lowlevel_analysis_manifest.json"
COARSE = ROOT / "measurements/results/pultec_lf/joint_grid_44k1_coarse_manifest.json"
INTEGER = ROOT / "measurements/results/pultec_lf/joint_grid_44k1_integer_manifest.json"
FLAT = ROOT / "measurements/results/pultec_lf/level_sweep_control_v2/flat-m36-44k1-sweep.csv"
OUT = ROOT / "measurements/results/pultec_lf/joint_magnitude_residual_probe.json"
SR = 44100


def curve(path):
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    freq = np.array([float(r["freq_hz"]) for r in rows])
    db = np.array([float(r["magnitude_db"]) for r in rows])
    phase = np.deg2rad([float(r["phase_deg"]) for r in rows])
    return freq, 10 ** (db / 20) * np.exp(1j * phase), db


def main():
    targets = {}
    axes = {}
    for row in json.loads(BASE.read_text(encoding="utf-8"))["rows"]:
        if row["sample_rate_hz"] != SR:
            continue
        c = row["configuration"]
        key = (c["lf_cps_hz"], float(c["lf_boost_ui"]), float(c["lf_atten_ui"]))
        sampled = curve(ROOT / row["analysis_csv"])
        if key[1] == 0.0 or key[2] == 0.0:
            axes[key] = sampled
        else:
            targets[key] = sampled
    for manifest in (COARSE, INTEGER):
        rows = json.loads(manifest.read_text(encoding="utf-8"))["rows"].values()
        for row in rows:
            if row.get("status") != "complete":
                continue
            key = (row["lf_cps_hz"], float(row["lf_boost_ui"]), float(row["lf_atten_ui"]))
            targets[key] = curve(ROOT / row["analysis_csv"])
    flat = curve(FLAT)
    reports = {}
    for cps in (20, 30, 60, 100):
        records = []
        for boost in range(2, 11, 2):
            for atten in range(2, 11, 2):
                if (boost, atten) in ((8, 2), (2, 8)):
                    continue
                key = (cps, float(boost), float(atten))
                freq, joint, joint_db = targets[key]
                _, bcurve, bdb = axes[(cps, float(boost), 0.0)]
                _, acurve, adb = axes[(cps, 0.0, float(atten))]
                residual_complex = joint - bcurve - acurve + flat[1]
                residual_db = joint_db - bdb - adb + flat[2]
                records.append((boost, atten, freq, residual_complex, residual_db))
        coords = np.array([[b / 2, a / 2] for b, a, *_ in records])
        complex_values = np.array([np.r_[z.real, z.imag] for *_, z, _ in records])
        db_values = np.array([r for *_, r in records])
        polar_db_values, polar_phase_values = [], []
        for boost, atten, freq, *_ in records:
            measured = targets[(cps, float(boost), float(atten))][1]
            base = axes[(cps, float(boost), 0.0)][1] + axes[(cps, 0.0, float(atten))][1] - flat[1]
            ratio = measured / base
            polar_db_values.append(20 * np.log10(np.maximum(np.abs(ratio), 1e-12)))
            polar_phase_values.append(np.unwrap(np.angle(ratio)))
        polar_db_values = np.asarray(polar_db_values)
        polar_phase_values = np.asarray(polar_phase_values)
        for kernel in ("cubic", "thin_plate_spline", "multiquadric"):
            options = {"epsilon": 1.0} if kernel == "multiquadric" else {}
            complex_rbf = RBFInterpolator(coords, complex_values, kernel=kernel, degree=1, **options)
            db_rbf = RBFInterpolator(coords, db_values, kernel=kernel, degree=1, **options)
            polar_db_rbf = RBFInterpolator(coords, polar_db_values, kernel=kernel, degree=1, **options)
            polar_phase_rbf = RBFInterpolator(coords, polar_phase_values, kernel=kernel, degree=1, **options)
            train_mag, hold_mag, train_cx, hold_cx, hold_polar, hold_polar_phase = [], [], [], [], [], []
            for (fit_b, fit_a, freq, *_rest) in records:
                vec = complex_rbf([[fit_b / 2, fit_a / 2]])[0]
                zres = vec[:len(freq)] + 1j * vec[len(freq):]
                pred = axes[(cps, float(fit_b), 0.0)][1] + axes[(cps, 0.0, float(fit_a))][1] - flat[1] + zres
                target = targets[(cps, float(fit_b), float(fit_a))]
                train_cx.append(20 * np.log10(np.maximum(np.abs(pred), 1e-12)) - target[2])
                dz = db_rbf([[fit_b / 2, fit_a / 2]])[0]
                pred_db = axes[(cps, float(fit_b), 0.0)][2] + axes[(cps, 0.0, float(fit_a))][2] - flat[2] + dz
                train_mag.append(pred_db - target[2])
            for (tcps, b, a), (freq, target, target_db) in targets.items():
                if tcps != cps or b == 0 or a == 0:
                    continue
                if b % 2 == 0 and a % 2 == 0 and (b, a) not in ((8, 2), (2, 8)):
                    continue
                vec = complex_rbf([[b / 2, a / 2]])[0]
                zres = vec[:len(freq)] + 1j * vec[len(freq):]
                pred = axes[(cps, b, 0.0)][1] + axes[(cps, 0.0, a)][1] - flat[1] + zres
                hold_cx.append(20 * np.log10(np.maximum(np.abs(pred), 1e-12)) - target_db)
                dz = db_rbf([[b / 2, a / 2]])[0]
                pred_db = axes[(cps, b, 0.0)][2] + axes[(cps, 0.0, a)][2] - flat[2] + dz
                hold_mag.append(pred_db - target_db)
                corr_db = polar_db_rbf([[b / 2, a / 2]])[0]
                corr_phase = polar_phase_rbf([[b / 2, a / 2]])[0]
                base = axes[(cps, b, 0.0)][1] + axes[(cps, 0.0, a)][1] - flat[1]
                pred_polar = base * 10 ** (corr_db / 20) * np.exp(1j * corr_phase)
                hold_polar.append(20 * np.log10(np.maximum(np.abs(pred_polar), 1e-12)) - target_db)
                hold_polar_phase.append(np.unwrap(np.angle(pred_polar * np.conj(target))) * 180 / np.pi)
            freq = flat[0]
            bands = {}
            for lo, hi, limit in ((20, 100, .20), (100, 1000, .15), (1000, 18000, .10)):
                mask = (freq >= lo) & (freq <= hi)
                bands[f"{lo}-{hi}"] = {
                    "complex_train_fail": int(np.sum(np.max(np.abs(np.array(train_cx)[:, mask]), axis=1) > limit)),
                    "complex_holdout_fail": int(np.sum(np.max(np.abs(np.array(hold_cx)[:, mask]), axis=1) > limit)),
                    "magnitude_train_fail": int(np.sum(np.max(np.abs(np.array(train_mag)[:, mask]), axis=1) > limit)),
                    "magnitude_holdout_fail": int(np.sum(np.max(np.abs(np.array(hold_mag)[:, mask]), axis=1) > limit)),
                    "polar_magnitude_holdout_fail": int(np.sum(np.max(np.abs(np.array(hold_polar)[:, mask]), axis=1) > limit)),
                    "polar_phase_holdout_fail_2deg": int(np.sum(np.max(np.abs(np.array(hold_polar_phase)[:, mask]), axis=1) > 2.0)),
                    "tolerance_db": limit}
            reports[f"{cps}/{kernel}"] = {"train_count": len(train_mag), "holdout_count": len(hold_mag), "bands": bands}
    result = {"schema": "altair-eq.pultec-lf-joint-magnitude-residual-probe/1",
              "sample_rate_hz": SR, "axis_source": "measured single-axis response",
              "training_nodes_per_cps": 23, "holdout_nodes_per_cps": 77,
              "results": reports}
    OUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    print(f"output: {OUT}")


if __name__ == "__main__":
    main()
