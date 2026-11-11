#!/usr/bin/env python3
"""Check rank-two SOS mode fits against withheld joint controls for fitted CPS cases."""
import csv
import json
from pathlib import Path

import numpy as np
from scipy.interpolate import RBFInterpolator

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "measurements/results/pultec_lf/lowlevel_analysis_manifest.json"
COARSE = ROOT / "measurements/results/pultec_lf/joint_grid_44k1_coarse_manifest.json"
INTEGER = ROOT / "measurements/results/pultec_lf/joint_grid_44k1_integer_manifest.json"
MODES = ROOT / "measurements/results/pultec_lf/joint_residual_svd_mode_16sec_fits.json"
FLAT = ROOT / "measurements/results/pultec_lf/level_sweep_control_v2/flat-m36-44k1-sweep.csv"
OUT = MODES.with_name(f"{MODES.stem}_reconstruction.json")
SR = 44100


def curve(path):
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    freq = np.array([float(r["freq_hz"]) for r in rows])
    db = np.array([float(r["magnitude_db"]) for r in rows])
    phase = np.deg2rad([float(r["phase_deg"]) for r in rows])
    return freq, 10 ** (db / 20) * np.exp(1j * phase), db


def response(parameters, freq):
    parameters = np.asarray(parameters)
    q = np.exp(-1j * 2 * np.pi * freq / SR)
    h = np.full(q.shape, np.exp(parameters[0]), dtype=np.complex128)
    for index in range((len(parameters) - 1) // 4):
        rp, tp, rz, tz = parameters[1 + index * 4: 5 + index * 4]
        h *= (1 - 2 * rz * np.cos(tz) * q + rz * rz * q * q) / (1 - 2 * rp * np.cos(tp) * q + rp * rp * q * q)
    return h


def metric(pred, target, target_db, freq):
    mag_error = 20 * np.log10(np.maximum(np.abs(pred), 1e-12)) - target_db
    phase_error = np.angle(pred * np.conj(target)) * 180 / np.pi
    bands = {}
    for lo, hi in ((20, 100), (100, 1000), (1000, 18000)):
        mask = (freq >= lo) & (freq < hi if hi < 18000 else freq <= hi)
        bands[f"{lo}-{hi}"] = float(np.max(np.abs(mag_error[mask])))
    p = float(np.max(np.abs(phase_error)))
    passed = (bands["20-100"] <= .2 and bands["100-1000"] <= .15
              and bands["1000-18000"] <= .1 and p <= 2)
    return {"pass": bool(passed), "band_max_magnitude_error_db": bands,
            "max_phase_error_deg": p}


def main():
    targets = {}
    for row in json.loads(BASE.read_text(encoding="utf-8"))["rows"]:
        if row["sample_rate_hz"] == SR:
            c = row["configuration"]
            targets[(c["lf_cps_hz"], float(c["lf_boost_ui"]), float(c["lf_atten_ui"]))] = curve(ROOT / row["analysis_csv"])
    for manifest in (COARSE, INTEGER):
        for row in json.loads(manifest.read_text(encoding="utf-8"))["rows"].values():
            if row.get("status") == "complete":
                targets[(row["lf_cps_hz"], float(row["lf_boost_ui"]), float(row["lf_atten_ui"]))] = curve(ROOT / row["analysis_csv"])
    flat = curve(FLAT)
    mode_fits = json.loads(MODES.read_text(encoding="utf-8"))["results"]
    by_cps = {}
    for fit in mode_fits:
        by_cps.setdefault(int(fit["id"][3:].split("-")[0]), []).append(fit)

    results = []
    for cps, fits in by_cps.items():
        if len(fits) != 2:
            continue
        freq = flat[0]
        train_coords, train_residuals = [], []
        for b in range(0, 11, 2):
            for a in range(0, 11, 2):
                if (b, a) in ((8, 2), (2, 8)):
                    continue
                if b == 0 or a == 0:
                    residual = np.zeros_like(flat[1])
                else:
                    joint = targets[(cps, float(b), float(a))][1]
                    boost = targets[(cps, float(b), 0.0)][1]
                    atten = targets[(cps, 0.0, float(a))][1]
                    residual = joint - boost - atten + flat[1]
                train_coords.append([b / 2.0, a / 2.0])
                train_residuals.append(residual)
        train_residuals = np.asarray(train_residuals)
        matrix = np.concatenate([train_residuals.real, train_residuals.imag], axis=1)
        left, singular, _ = np.linalg.svd(matrix, full_matrices=False)
        coefficients = left[:, :2] * singular[:2]
        model = RBFInterpolator(np.asarray(train_coords), coefficients, kernel="cubic", degree=1)
        mode_responses = np.asarray([response(f["parameters"], freq) for f in sorted(fits, key=lambda x: x["id"])])
        for b in range(1, 11):
            for a in range(1, 11):
                if b % 2 == 0 and a % 2 == 0 and (b, a) not in ((8, 2), (2, 8)):
                    continue
                key = (cps, float(b), float(a))
                if key not in targets:
                    continue
                co = model(np.array([[b / 2.0, a / 2.0]]))[0]
                correction = co @ mode_responses
                base = targets[(cps, float(b), 0.0)][1] + targets[(cps, 0.0, float(a))][1] - flat[1]
                results.append({"id": f"cps{cps}-b{b:02d}-a{a:02d}",
                                **metric(base + correction, targets[key][1], targets[key][2], freq)})
    summary = {str(cps): {"pass": sum(r["pass"] for r in results if r["id"].startswith(f"cps{cps}-")),
                          "total": sum(r["id"].startswith(f"cps{cps}-") for r in results),
                          "max_phase_error_deg": max(r["max_phase_error_deg"] for r in results if r["id"].startswith(f"cps{cps}-")),
                          "max_band_errors_db": {band: max(r["band_max_magnitude_error_db"][band] for r in results if r["id"].startswith(f"cps{cps}-"))
                                                  for band in ("20-100", "100-1000", "1000-18000")}}
               for cps in by_cps if len(by_cps[cps]) == 2}
    OUT.write_text(json.dumps({"schema": "altair-eq.pultec-lf-svd-mode-sos-reconstruction/1",
                               "method": "cubic control RBF weights applied to 12-section SOS fits of two residual modes",
                               "sample_rate_hz": SR, "summary": summary, "results": results},
                              ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"details: {OUT}")


if __name__ == "__main__":
    main()
