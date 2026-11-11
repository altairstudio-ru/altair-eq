#!/usr/bin/env python3
"""Test whether explicit all-pass sections can reduce phase residuals."""
import csv
import json
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares

import fit_pultec_lf_stable_sos as fitter


ROOT = Path(__file__).resolve().parents[2]
FIT_SET = ROOT / "measurements/results/pultec_lf/stable_sos_fits.json"
OUT = ROOT / "measurements/results/pultec_lf/allpass_phase_probe.json"


def allpass(parameters, omega):
    q = np.exp(-1j * omega)
    a = parameters[0]
    h = (a + q) / (1 + a * q)
    for index in range(2):
        radius, angle = parameters[1 + 2 * index:3 + 2 * index]
        cosine = 2 * radius * np.cos(angle)
        radius2 = radius * radius
        h *= (radius2 - cosine * q + q * q) / (1 - cosine * q + radius2 * q * q)
    return h


def main():
    rows = json.loads(FIT_SET.read_text(encoding="utf-8"))["results"]
    # Include the largest observed phase residuals and one high-frequency-magnitude failure.
    failures = sorted((row for row in rows if not row["pass"]),
                      key=lambda row: row["max_phase_error_deg"], reverse=True)[:8]
    results = []
    lower = np.array([-0.9999, 0.01, 1e-5, 0.01, 1e-5])
    upper = np.array([0.9999, 0.9999, np.pi, 0.9999, np.pi])
    for row in failures:
        path = ROOT / row["source"]
        with path.open(newline="", encoding="utf-8") as stream:
            source = list(csv.DictReader(stream))
        freq = np.array([float(item["freq_hz"]) for item in source])
        phase = np.deg2rad([float(item["phase_deg"]) for item in source])
        omega = 2 * np.pi * freq / row["sample_rate_hz"]
        model = fitter.response(np.asarray(row["parameters"]), omega)
        start = np.array([0.9, 0.97, 0.05, 0.97, 1.0])

        def residual(parameters):
            fitted_phase = np.unwrap(np.angle(allpass(parameters, omega) * model))
            return (fitted_phase - phase) * 180 / np.pi

        fit = least_squares(residual, start, bounds=(lower, upper), max_nfev=4000,
                            x_scale="jac", ftol=1e-10, xtol=1e-10, gtol=1e-10)
        before = (np.unwrap(np.angle(model)) - phase) * 180 / np.pi
        after = residual(fit.x)
        result = {"id": row["id"], "parameters": fit.x.tolist(),
                  "phase_max_before_deg": float(np.max(np.abs(before))),
                  "phase_rms_before_deg": float(np.sqrt(np.mean(before ** 2))),
                  "phase_max_after_deg": float(np.max(np.abs(after))),
                  "phase_rms_after_deg": float(np.sqrt(np.mean(after ** 2))),
                  "magnitude_errors_db": row["band_max_magnitude_error_db"]}
        results.append(result)
        print(f"{row['id']}: phase {result['phase_max_before_deg']:.3f} -> "
              f"{result['phase_max_after_deg']:.3f} deg max; "
              f"RMS {result['phase_rms_before_deg']:.3f} -> {result['phase_rms_after_deg']:.3f}",
              flush=True)
    OUT.write_text(json.dumps({"schema": "altair-eq.allpass-probe/1", "allpass_sections": 3,
                               "source_fit_set": str(FIT_SET.relative_to(ROOT)).replace("\\", "/"),
                               "results": results}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"saved {len(results)} probes -> {OUT}")


if __name__ == "__main__":
    main()
