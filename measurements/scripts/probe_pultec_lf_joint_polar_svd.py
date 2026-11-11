#!/usr/bin/env python3
"""Measure spectral rank needed for polar joint-interaction interpolation."""
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
OUT = ROOT / "measurements/results/pultec_lf/joint_polar_svd_probe.json"
SR = 44100


def curve(path):
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    freq = np.array([float(r["freq_hz"]) for r in rows])
    db = np.array([float(r["magnitude_db"]) for r in rows])
    phase = np.deg2rad([float(r["phase_deg"]) for r in rows])
    return freq, 10 ** (db / 20) * np.exp(1j * phase), db


def main():
    targets, axes = {}, {}
    for row in json.loads(BASE.read_text(encoding="utf-8"))["rows"]:
        if row["sample_rate_hz"] != SR:
            continue
        c = row["configuration"]
        key = (c["lf_cps_hz"], float(c["lf_boost_ui"]), float(c["lf_atten_ui"]))
        (axes if key[1] == 0 or key[2] == 0 else targets)[key] = curve(ROOT / row["analysis_csv"])
    for manifest in (COARSE, INTEGER):
        for row in json.loads(manifest.read_text(encoding="utf-8"))["rows"].values():
            if row.get("status") == "complete":
                key = (row["lf_cps_hz"], float(row["lf_boost_ui"]), float(row["lf_atten_ui"]))
                targets[key] = curve(ROOT / row["analysis_csv"])
    flat = curve(FLAT)
    summary = {}
    for cps in (20, 30, 60, 100):
        coords, logmag, phase = [], [], []
        train_rows = []
        for b in range(2, 11, 2):
            for a in range(2, 11, 2):
                if (b, a) in ((8, 2), (2, 8)):
                    continue
                freq, joint, joint_db = targets[(cps, float(b), float(a))]
                base = axes[(cps, float(b), 0.0)][1] + axes[(cps, 0.0, float(a))][1] - flat[1]
                ratio = joint / base
                coords.append([b / 2, a / 2])
                logmag.append(20 * np.log10(np.maximum(np.abs(ratio), 1e-12)))
                phase.append(np.unwrap(np.angle(ratio)))
                train_rows.append((b, a, freq, joint, joint_db, base))
        coords = np.asarray(coords)
        logmag, phase = np.asarray(logmag), np.asarray(phase)
        u_m, s_m, vh_m = np.linalg.svd(logmag, full_matrices=False)
        u_p, s_p, vh_p = np.linalg.svd(phase, full_matrices=False)
        result = {"magnitude_singular_energy_90_rank": int(np.searchsorted(np.cumsum(s_m*s_m)/np.sum(s_m*s_m), .9)+1),
                  "phase_singular_energy_90_rank": int(np.searchsorted(np.cumsum(s_p*s_p)/np.sum(s_p*s_p), .9)+1),
                  "ranks": {}, "complex_log_ranks": {}}
        for rank in (1, 2, 3, 4, 6, 8, 12, 16, 23):
            if rank > len(s_m):
                continue
            cm, cp = u_m[:, :rank] * s_m[:rank], u_p[:, :rank] * s_p[:rank]
            for kernel, options in (("cubic", {}), ("thin_plate_spline", {}), ("multiquadric", {"epsilon": 1.0})):
                rm = RBFInterpolator(coords, cm, kernel=kernel, degree=1, **options)
                rp = RBFInterpolator(coords, cp, kernel=kernel, degree=1, **options)
                errors, phases, train_errors, train_phases = [], [], [], []
                for idx, (b0, a0, freq0, joint0, joint_db0, base0) in enumerate(train_rows):
                    q0 = np.array([[b0 / 2, a0 / 2]])
                    md0 = rm(q0)[0] @ vh_m[:rank]
                    ph0 = rp(q0)[0] @ vh_p[:rank]
                    pred0 = base0 * 10 ** (md0 / 20) * np.exp(1j * ph0)
                    train_errors.append(20 * np.log10(np.maximum(np.abs(pred0), 1e-12)) - joint_db0)
                    train_phases.append(np.unwrap(np.angle(pred0 * np.conj(joint0))) * 180 / np.pi)
                for (tcps, b, a), (freq, joint, joint_db) in targets.items():
                    if tcps != cps or b == 0 or a == 0:
                        continue
                    if b % 2 == 0 and a % 2 == 0 and (b, a) not in ((8, 2), (2, 8)):
                        continue
                    q = np.array([[b / 2, a / 2]])
                    md = rm(q)[0] @ vh_m[:rank]
                    ph = rp(q)[0] @ vh_p[:rank]
                    base = axes[(cps, b, 0.0)][1] + axes[(cps, 0.0, a)][1] - flat[1]
                    pred = base * 10 ** (md / 20) * np.exp(1j * ph)
                    errors.append(20 * np.log10(np.maximum(np.abs(pred), 1e-12)) - joint_db)
                    phases.append(np.unwrap(np.angle(pred * np.conj(joint))) * 180 / np.pi)
                errors, phases = np.asarray(errors), np.asarray(phases)
                train_errors, train_phases = np.asarray(train_errors), np.asarray(train_phases)
                hi = (freq >= 1000) & (freq <= 18000)
                lo = (freq >= 20) & (freq <= 100)
                mid = (freq > 100) & (freq < 1000)
                result["ranks"][f"{rank}/{kernel}"] = {
                    "holdout_count": len(errors),
                    "high_mag_fail_0p1db": int(np.sum(np.max(np.abs(errors[:, hi]), axis=1) > .1)),
                    "high_phase_fail_2deg": int(np.sum(np.max(np.abs(phases[:, hi]), axis=1) > 2)),
                    "train_high_mag_fail_0p1db": int(np.sum(np.max(np.abs(train_errors[:, hi]), axis=1) > .1)),
                    "train_high_phase_fail_2deg": int(np.sum(np.max(np.abs(train_phases[:, hi]), axis=1) > 2)),
                    "low_mag_fail_0p2db": int(np.sum(np.max(np.abs(errors[:, lo]), axis=1) > .2)),
                    "mid_mag_fail_0p15db": int(np.sum(np.max(np.abs(errors[:, mid]), axis=1) > .15)),
                    "high_mag_max_abs_db": float(np.max(np.abs(errors[:, hi]))),
                    "high_mag_p90_db": float(np.percentile(np.max(np.abs(errors[:, hi]), axis=1), 90)),
                    "high_phase_max_abs_deg": float(np.max(np.abs(phases[:, hi]))),
                    "train_high_mag_max_abs_db": float(np.max(np.abs(train_errors[:, hi]))),
                    "train_high_phase_max_abs_deg": float(np.max(np.abs(train_phases[:, hi])))}
        complex_log = logmag * (np.log(10) / 20) + 1j * phase
        uc, sc, vhc = np.linalg.svd(complex_log, full_matrices=False)
        rank1_coeff = uc[:, 0] * sc[0]
        coeff_rotation = np.exp(-1j * np.angle(np.sum(rank1_coeff ** 2)) / 2)
        rotated_coeff = rank1_coeff * coeff_rotation
        result["complex_log_rank1_control_coefficient"] = {
            "rotated_imag_rms_over_real_rms": float(np.sqrt(np.mean(rotated_coeff.imag**2)) /
                                                       max(np.sqrt(np.mean(rotated_coeff.real**2)), 1e-12)),
            "rotated_imag_max": float(np.max(np.abs(rotated_coeff.imag))),
            "real_min": float(np.min(rotated_coeff.real)), "real_max": float(np.max(rotated_coeff.real))}
        for rank in (1, 2, 3, 4):
            coeff = uc[:, :rank] * sc[:rank]
            rbf = RBFInterpolator(coords, coeff, kernel="cubic", degree=1)
            train_err, train_phase, hold_err, hold_phase = [], [], [], []
            for b0, a0, freq0, joint0, joint_db0, base0 in train_rows:
                logcorr = rbf([[b0/2, a0/2]])[0] @ vhc[:rank]
                pred = base0 * np.exp(logcorr)
                train_err.append(20*np.log10(np.maximum(np.abs(pred), 1e-12))-joint_db0)
                train_phase.append(np.unwrap(np.angle(pred*np.conj(joint0)))*180/np.pi)
            for (tcps, b, a), (freq0, joint0, joint_db0) in targets.items():
                if tcps != cps or b == 0 or a == 0:
                    continue
                if b % 2 == 0 and a % 2 == 0 and (b, a) not in ((8, 2), (2, 8)):
                    continue
                logcorr = rbf([[b/2, a/2]])[0] @ vhc[:rank]
                base0 = axes[(cps, b, 0.0)][1] + axes[(cps, 0.0, a)][1] - flat[1]
                pred = base0 * np.exp(logcorr)
                hold_err.append(20*np.log10(np.maximum(np.abs(pred), 1e-12))-joint_db0)
                hold_phase.append(np.unwrap(np.angle(pred*np.conj(joint0)))*180/np.pi)
            train_err, train_phase = np.asarray(train_err), np.asarray(train_phase)
            hold_err, hold_phase = np.asarray(hold_err), np.asarray(hold_phase)
            hi = (freq >= 1000) & (freq <= 18000)
            low = (freq >= 20) & (freq <= 100)
            mid = (freq > 100) & (freq < 1000)
            result["complex_log_ranks"][str(rank)] = {
                "holdout_high_mag_fail": int(np.sum(np.max(np.abs(hold_err[:,hi]),axis=1)>.1)),
                "holdout_high_phase_fail": int(np.sum(np.max(np.abs(hold_phase[:,hi]),axis=1)>2)),
                "train_high_mag_fail": int(np.sum(np.max(np.abs(train_err[:,hi]),axis=1)>.1)),
                "train_high_phase_fail": int(np.sum(np.max(np.abs(train_phase[:,hi]),axis=1)>2)),
                "holdout_low_mag_fail": int(np.sum(np.max(np.abs(hold_err[:,low]),axis=1)>.2)),
                "holdout_mid_mag_fail": int(np.sum(np.max(np.abs(hold_err[:,mid]),axis=1)>.15)),
                "holdout_high_mag_max_db": float(np.max(np.abs(hold_err[:,hi]))),
                "holdout_high_phase_max_deg": float(np.max(np.abs(hold_phase[:,hi])))}
        summary[str(cps)] = result
    OUT.write_text(json.dumps({"schema": "altair-eq.pultec-lf-joint-polar-svd-probe/1",
                               "sample_rate_hz": SR, "results": summary}, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2)); print(f"output: {OUT}")


if __name__ == "__main__":
    main()
