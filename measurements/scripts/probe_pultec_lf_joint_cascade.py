#!/usr/bin/env python3
"""Test causal separability of measured Pultec LF Boost and Atten responses."""
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
OUT = ROOT / "measurements/results/pultec_lf/joint_cascade_probe.json"
MODE_DIR = ROOT / "measurements/results/pultec_lf/joint_residual_svd_modes"
SR = 44100


def curve(path):
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    freq = np.array([float(row["freq_hz"]) for row in rows])
    db = np.array([float(row["magnitude_db"]) for row in rows])
    phase = np.deg2rad([float(row["phase_deg"]) for row in rows])
    return freq, 10 ** (db / 20) * np.exp(1j * phase), db


def metric(pred, target, reference_db, freq):
    magnitude_error = 20 * np.log10(np.maximum(np.abs(pred), 1e-12)) - reference_db
    phase_error = np.angle(pred * np.conj(target)) * 180 / np.pi
    bands = {}
    for lo, hi in ((20, 100), (100, 1000), (1000, 18000)):
        mask = (freq >= lo) & (freq < hi if hi < 18000 else freq <= hi)
        bands[f"{lo}-{hi}"] = float(np.max(np.abs(magnitude_error[mask])))
    phase = float(np.max(np.abs(phase_error)))
    passed = (bands["20-100"] <= .2 and bands["100-1000"] <= .15
              and bands["1000-18000"] <= .1 and phase <= 2)
    return {"pass": bool(passed), "magnitude_error_db": bands, "phase_error_deg": phase}


def main():
    flat = curve(FLAT)
    data = {}
    for row in json.loads(BASE.read_text(encoding="utf-8"))["rows"]:
        if row["sample_rate_hz"] != SR:
            continue
        cfg = row["configuration"]
        key = (cfg["lf_cps_hz"], float(cfg["lf_boost_ui"]), float(cfg["lf_atten_ui"]))
        data[key] = curve(ROOT / row["analysis_csv"])
    for manifest in (COARSE, INTEGER):
        for row in json.loads(manifest.read_text(encoding="utf-8"))["rows"].values():
            if row.get("status") != "complete":
                continue
            key = (row["lf_cps_hz"], float(row["lf_boost_ui"]), float(row["lf_atten_ui"]))
            data[key] = curve(ROOT / row["analysis_csv"])
    for cps in (20, 30, 60, 100):
        data[(cps, 0.0, 0.0)] = flat

    results = []
    heldout_ids = []
    kernels = ("thin_plate_spline", "cubic", "quintic", "multiquadric")
    compressed_ranks = (2, 4, 6, 8, 12, 16, 24, 34)
    for cps in (20, 30, 60, 100):
        train_coords = np.array([[b, a] for b in range(0, 11, 2) for a in range(0, 11, 2)
                                 if (cps, float(b), float(a)) in data
                                 and (b, a) not in ((8, 2), (2, 8))], dtype=float)
        train_residuals = []
        for b, a in train_coords:
            joint = data[(cps, float(b), float(a))][1]
            boost = data[(cps, float(b), 0.0)][1]
            atten = data[(cps, 0.0, float(a))][1]
            train_residuals.append(joint - boost - atten + flat[1])
        train_residuals = np.asarray(train_residuals)
        residual_values = np.concatenate([train_residuals.real, train_residuals.imag], axis=1)
        models = {kernel: RBFInterpolator(train_coords / 2.0, residual_values,
                                          kernel=kernel, degree=1 if kernel != "quintic" else 2,
                                          epsilon=1.0)
                  for kernel in kernels}
        left, singular, right = np.linalg.svd(residual_values, full_matrices=False)
        MODE_DIR.mkdir(parents=True, exist_ok=True)
        mode_rows = []
        for mode_index in range(2):
            vector = right[mode_index, :len(flat[0])] + 1j * right[mode_index, len(flat[0]):]
            mode_path = MODE_DIR / f"cps{cps}-mode{mode_index + 1:02d}.csv"
            with mode_path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.writer(stream)
                writer.writerow(("freq_hz", "magnitude_db", "phase_deg"))
                for hz, response in zip(flat[0], vector):
                    writer.writerow((f"{hz:.12g}", f"{20*np.log10(max(abs(response),1e-12)):.12g}",
                                     f"{np.angle(response,deg=True):.12g}"))
            mode_rows.append({"id": f"cps{cps}-mode{mode_index + 1:02d}",
                              "source": str(mode_path.relative_to(ROOT)).replace("\\", "/"),
                              "energy_fraction": float(singular[mode_index] ** 2 / np.sum(singular ** 2))})
        (MODE_DIR / f"cps{cps}-modes.json").write_text(
            json.dumps({"schema": "altair-eq.pultec-lf-residual-svd-modes/1",
                        "sample_rate_hz": SR, "basis_nodes": len(train_coords),
                        "modes": mode_rows}, indent=2) + "\n", encoding="utf-8")
        compressed_models = {}
        for rank in compressed_ranks:
            effective_rank = min(rank, len(singular))
            coordinates = train_coords / 2.0
            coefficients = left[:, :effective_rank] * singular[:effective_rank]
            compressed_models[rank] = (RBFInterpolator(coordinates, coefficients,
                                                         kernel="cubic", degree=1),
                                       right[:effective_rank])
        for b in range(1, 11):
            for a in range(1, 11):
                if b % 2 == 0 and a % 2 == 0 and (b, a) not in ((8, 2), (2, 8)):
                    continue
                key = (cps, float(b), float(a))
                if key not in data:
                    continue
                freq, target, target_db = data[key]
                boost = data[(cps, float(b), 0.0)][1]
                atten = data[(cps, 0.0, float(a))][1]
                base = boost + atten - flat[1]
                heldout_ids.append(f"cps{cps}-b{b:02d}-a{a:02d}")
                for kernel, model in models.items():
                    correction = model(np.array([[b / 2.0, a / 2.0]]))[0]
                    residual = correction[:len(freq)] + 1j * correction[len(freq):]
                    results.append({"id": f"cps{cps}-b{b:02d}-a{a:02d}",
                                    "model": f"additive_plus_residual_{kernel}",
                                    **metric(base + residual, target, target_db, freq)})
                for rank, (model, modes) in compressed_models.items():
                    coefficients = model(np.array([[b / 2.0, a / 2.0]]))[0]
                    correction = coefficients @ modes
                    residual = correction[:len(freq)] + 1j * correction[len(freq):]
                    results.append({"id": f"cps{cps}-b{b:02d}-a{a:02d}",
                                    "model": f"additive_plus_residual_cubic_svd_{rank}",
                                    **metric(base + residual, target, target_db, freq)})

    for (cps, boost, atten), (freq, target, target_db) in data.items():
        if boost <= 0 or atten <= 0:
            continue
        b = data.get((cps, boost, 0.0))
        a = data.get((cps, 0.0, atten))
        if b is None or a is None:
            continue
        for name, predicted in (("cascade", b[1] * a[1] / flat[1]),
                                ("additive_complex", b[1] + a[1] - flat[1])):
            results.append({"id": f"cps{cps}-b{boost:g}-a{atten:g}", "model": name,
                            **metric(predicted, target, target_db, freq)})
    summary = {}
    model_names = ("cascade", "additive_complex",
                   *(f"additive_plus_residual_{kernel}" for kernel in kernels),
                   *(f"additive_plus_residual_cubic_svd_{rank}" for rank in compressed_ranks))
    for name in model_names:
        subset = [row for row in results if row["model"] == name]
        summary[name] = {
            "pass": sum(row["pass"] for row in subset), "total": len(subset),
            "max_phase_error_deg": max(row["phase_error_deg"] for row in subset),
            "max_magnitude_error_db": {band: max(row["magnitude_error_db"][band] for row in subset)
                                       for band in ("20-100", "100-1000", "1000-18000")},
        }
    OUT.write_text(json.dumps({"schema": "altair-eq.pultec-lf-joint-cascade-probe/1",
                               "method": "compose measured single-axis complex responses and interpolate the measured interaction residual on even-grid nodes",
                               "sample_rate_hz": SR, "heldout_count": len(set(heldout_ids)),
                               "summary": summary, "results": results},
                              indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"details: {OUT}")


if __name__ == "__main__":
    main()
