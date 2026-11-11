#!/usr/bin/env python3
"""Validate interpolated causal multiplicative correction on LF joint holdouts."""
import csv
import json
import sys
from pathlib import Path

import numpy as np
from scipy.interpolate import RBFInterpolator

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "measurements/scripts"))
import plot_pultec_lf_joint_holdout_diagnostics as model

BASE = ROOT / "measurements/results/pultec_lf/lowlevel_analysis_manifest.json"
COARSE = ROOT / "measurements/results/pultec_lf/joint_grid_44k1_coarse_manifest.json"
INTEGER = ROOT / "measurements/results/pultec_lf/joint_grid_44k1_integer_manifest.json"
AXIS = ROOT / "measurements/results/pultec_lf/axis_integer_8sos_fits.json"
FLAT_FIT = ROOT / "measurements/results/pultec_lf/flat_reference_fit.json"
JOINT = ROOT / "measurements/results/pultec_lf/joint_multiplicative_sos_fits_6sec.json"
OUT = ROOT / "measurements/results/pultec_lf/joint_multiplicative_sos_probe"
SR = 44100


def main():
    targets = {}
    for row in json.loads(BASE.read_text(encoding="utf-8"))["rows"]:
        if row["sample_rate_hz"] != SR:
            continue
        c = row["configuration"]
        key = (c["lf_cps_hz"], float(c["lf_boost_ui"]), float(c["lf_atten_ui"]))
        if key[1] > 0 and key[2] > 0:
            targets[key] = model.curve(ROOT / row["analysis_csv"])
    for manifest in (COARSE, INTEGER):
        for row in json.loads(manifest.read_text(encoding="utf-8"))["rows"].values():
            if row.get("status") == "complete":
                targets[(row["lf_cps_hz"], float(row["lf_boost_ui"]), float(row["lf_atten_ui"]))] = model.curve(ROOT / row["analysis_csv"])
    axis = {}
    for row in json.loads(AXIS.read_text(encoding="utf-8"))["results"]:
        c = row["configuration"]
        axis[(c["lf_cps_hz"], float(c["lf_boost_ui"]), float(c["lf_atten_ui"]))] = row
    flat_params = json.loads(FLAT_FIT.read_text(encoding="utf-8"))["result"]["parameters"]
    flat_freq, _, _ = model.curve(ROOT / "measurements/results/pultec_lf/level_sweep_control_v2/flat-m36-44k1-sweep.csv")
    fits = json.loads(JOINT.read_text(encoding="utf-8"))["results"]
    by_cps = {}
    for row in fits:
        by_cps.setdefault(int(row["key"][0]), {})[tuple(row["key"])] = row
    all_metrics = {}
    all_curves = []
    for cps, rows in by_cps.items():
        coords, vectors = [], []
        for b in range(0, 11, 2):
            for a in range(0, 11, 2):
                if (b, a) in ((8, 2), (2, 8)):
                    continue
                if b == 0 or a == 0:
                    correction = np.ones_like(flat_freq, dtype=np.complex128)
                else:
                    item = rows[(cps, float(b), float(a))]
                    correction = model.response(item["parameters"], flat_freq, item["sections"])
                coords.append([b / 2, a / 2])
                vectors.append(np.r_[correction.real, correction.imag])
        omega = 2 * np.pi * flat_freq / SR
        for kernel, options in (("cubic", {}), ("thin_plate_spline", {}), ("multiquadric", {"epsilon": 1.0})):
            rbf = RBFInterpolator(coords, vectors, kernel=kernel, degree=1, **options)
            train_err, train_phase, hold_err, hold_phase, hold_ids = [], [], [], [], []
            for (fcps, b, a), fit in rows.items():
                freq, target, target_db = targets[(fcps, float(b), float(a))]
                correction = model.response(fit["parameters"], freq, fit["sections"])
                base = (model.response(axis[(cps, float(b), 0.0)]["parameters"], freq, 8)
                        + model.response(axis[(cps, 0.0, float(a))]["parameters"], freq, 8)
                        - model.response(flat_params, freq, 6))
                pred = base * correction
                train_err.append(20 * np.log10(np.maximum(np.abs(pred), 1e-12)) - target_db)
                train_phase.append(np.unwrap(np.angle(pred * np.conj(target))) * 180 / np.pi)
            for (tcps, b, a), (freq, target, target_db) in targets.items():
                if tcps != cps or b == 0 or a == 0:
                    continue
                if b % 2 == 0 and a % 2 == 0 and (b, a) not in ((8, 2), (2, 8)):
                    continue
                vec = rbf([[b / 2, a / 2]])[0]
                correction = vec[:len(freq)] + 1j * vec[len(freq):]
                base = (model.response(axis[(cps, b, 0.0)]["parameters"], freq, 8)
                        + model.response(axis[(cps, 0.0, a)]["parameters"], freq, 8)
                        - model.response(flat_params, freq, 6))
                pred = base * correction
                err = 20 * np.log10(np.maximum(np.abs(pred), 1e-12)) - target_db
                phase = np.unwrap(np.angle(pred * np.conj(target))) * 180 / np.pi
                hold_err.append(err); hold_phase.append(phase); hold_ids.append((cps, b, a))
                all_curves.append((kernel, cps, b, a, freq, err, phase))
            train_err, hold_err = np.asarray(train_err), np.asarray(hold_err)
            train_phase, hold_phase = np.asarray(train_phase), np.asarray(hold_phase)
            bands = {}
            for lo, hi, mag_limit, phase_limit in ((20, 100, .20, 2.0), (100, 1000, .15, 2.0), (1000, 18000, .10, 2.0)):
                mask = (flat_freq >= lo) & (flat_freq <= hi)
                bands[f"{lo}-{hi}"] = {
                    "train_mag_fail": int(np.sum(np.max(np.abs(train_err[:, mask]), axis=1) > mag_limit)),
                    "holdout_mag_fail": int(np.sum(np.max(np.abs(hold_err[:, mask]), axis=1) > mag_limit)),
                    "train_phase_fail": int(np.sum(np.max(np.abs(train_phase[:, mask]), axis=1) > phase_limit)),
                    "holdout_phase_fail": int(np.sum(np.max(np.abs(hold_phase[:, mask]), axis=1) > phase_limit)),
                    "train_mag_max_db": float(np.max(np.abs(train_err[:, mask]))),
                    "holdout_mag_max_db": float(np.max(np.abs(hold_err[:, mask]))),
                    "train_phase_max_deg": float(np.max(np.abs(train_phase[:, mask]))),
                    "holdout_phase_max_deg": float(np.max(np.abs(hold_phase[:, mask])))}
            all_metrics[f"{cps}/{kernel}"] = {"train_count": len(train_err), "holdout_count": len(hold_err), "bands": bands}
    OUT.with_suffix(".json").write_text(json.dumps({"schema": "altair-eq.pultec-lf-joint-multiplicative-sos-probe/1",
                                                    "sample_rate_hz": SR, "results": all_metrics}, indent=2) + "\n", encoding="utf-8")
    with OUT.with_suffix(".csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["kernel", "cps", "boost", "atten", "freq_hz", "magnitude_error_db", "phase_error_deg"])
        for row in all_curves:
            w.writerows(zip([row[0]] * len(row[4]), [row[1]] * len(row[4]), [row[2]] * len(row[4]),
                               [row[3]] * len(row[4]), row[4], row[5], row[6]))
    print(json.dumps(all_metrics, indent=2)); print(f"output: {OUT.with_suffix('.json')}")


if __name__ == "__main__":
    main()
