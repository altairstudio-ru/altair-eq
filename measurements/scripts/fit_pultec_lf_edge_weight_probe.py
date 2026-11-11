#!/usr/bin/env python3
"""Check whether edge-focused fitting resolves boundary residuals."""
import csv
import json
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares

import fit_pultec_lf_stable_sos as fitter


ROOT = Path(__file__).resolve().parents[2]
FIT_SET = ROOT / "measurements/results/pultec_lf/stable_sos_fits.json"
OUT = ROOT / "measurements/results/pultec_lf/edge_weight_probe.json"


def main():
    rows = json.loads(FIT_SET.read_text(encoding="utf-8"))["results"]
    by_id = {row["id"]: row for row in rows}
    ids = ["boost_only-20-b080-a000-44k1-swp",
           "boost_atten_trick-60-b100-a100-44k1-swp",
           "boost_atten_trick-20-b020-a080-44k1-swp",
           "atten_only-60-b000-a060-44k1-swp"]
    results = []
    for rid in ids:
        row = by_id[rid]
        with (ROOT / row["source"]).open(newline="", encoding="utf-8") as stream:
            source = list(csv.DictReader(stream))
        freq = np.array([float(item["freq_hz"]) for item in source])
        target_db = np.array([float(item["magnitude_db"]) for item in source])
        target_phase = np.deg2rad([float(item["phase_deg"]) for item in source])
        target = 10 ** (target_db / 20) * np.exp(1j * target_phase)
        omega = 2 * np.pi * freq / row["sample_rate_hz"]
        edge = (freq <= 30) | (freq >= 17500)
        x0 = np.asarray(row["parameters"])
        candidates = []
        for weight in (2.0, 4.0, 8.0):
            weights = np.where(edge, weight, 1.0)

            def residual(parameters):
                ratio = fitter.response(parameters, omega) / target
                mag = 20 * np.log10(np.maximum(np.abs(ratio), 1e-12))
                phase = np.angle(ratio) * 180 / np.pi
                return np.concatenate([mag * weights, phase * 0.08 * weights])

            fit = least_squares(residual, x0, bounds=(np.array([-12.0] + [0.01, 1e-5, 0.01, 1e-5] * 4),
                                                       np.array([12.0] + [0.9999, np.pi, 5.0, np.pi] * 4)),
                                max_nfev=1800, x_scale="jac", ftol=1e-9, xtol=1e-9, gtol=1e-9)
            h = fitter.response(fit.x, omega)
            mag_error = 20 * np.log10(np.abs(h)) - target_db
            phase_error = np.angle(h * np.conj(target)) * 180 / np.pi
            band_errors = {}
            for lower, upper in ((20, 100), (100, 1000), (1000, 18000)):
                mask = (freq >= lower) & (freq < upper if upper < 18000 else freq <= upper)
                band_errors[f"{lower}-{upper}"] = float(np.max(np.abs(mag_error[mask])))
            candidate = {"edge_weight": weight, "parameters": fit.x.tolist(),
                         "band_max_magnitude_error_db": band_errors,
                         "max_phase_error_deg": float(np.max(np.abs(phase_error))),
                         "rms_phase_error_deg": float(np.sqrt(np.mean(phase_error ** 2))),
                         "evals": fit.nfev}
            candidate["pass"] = (candidate["max_phase_error_deg"] <= 2 and
                                  band_errors["20-100"] <= .20 and band_errors["100-1000"] <= .15 and
                                  band_errors["1000-18000"] <= .10)
            candidates.append(candidate)
            print(f"{rid} edge x{weight:g}: {'PASS' if candidate['pass'] else 'FAIL'} "
                  f"mag={band_errors} phase={candidate['max_phase_error_deg']:.3f} deg", flush=True)
        best = min(candidates, key=lambda item: max(item["max_phase_error_deg"] / 2,
                   item["band_max_magnitude_error_db"]["20-100"] / .20,
                   item["band_max_magnitude_error_db"]["100-1000"] / .15,
                   item["band_max_magnitude_error_db"]["1000-18000"] / .10))
        results.append({"id": rid, "baseline_pass": row["pass"], "baseline_phase_error_deg": row["max_phase_error_deg"],
                        "candidates": candidates, "best_edge_candidate": best})
    OUT.write_text(json.dumps({"schema": "altair-eq.edge-weight-probe/1", "source_fit_set": str(FIT_SET.relative_to(ROOT)).replace("\\", "/"),
                               "results": results}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"saved {len(results)} probes -> {OUT}")


if __name__ == "__main__":
    main()
