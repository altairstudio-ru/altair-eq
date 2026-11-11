#!/usr/bin/env python3
"""Probe whether the six-section fits retain accuracy with a safer pole bound."""
import csv
import json
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares

import fit_pultec_lf_stable_sos as fitter


ROOT = Path(__file__).resolve().parents[2]
FITS = ROOT / "measurements/results/pultec_lf/stable_sos_six_section_fits.json"
OUT = ROOT / "measurements/results/pultec_lf/pole_margin_probe.json"
MAX_RADIUS = 0.999


def main():
    fitter.SECTIONS = 6
    rows = json.loads(FITS.read_text(encoding="utf-8"))["results"]
    def score(row):
        e = row["band_max_magnitude_error_db"]
        return max(e["20-100"] / .20, e["100-1000"] / .15,
                   e["1000-18000"] / .10, row["max_phase_error_deg"] / 2)
    selected = sorted(rows, key=score, reverse=True)[:10]
    results = []
    lower = np.array([-12.0] + [0.01, 1e-5, 0.01, 1e-5] * 6)
    upper = np.array([12.0] + [MAX_RADIUS, np.pi, 5.0, np.pi] * 6)
    for row in selected:
        with (ROOT / row["source"]).open(newline="", encoding="utf-8") as stream:
            source = list(csv.DictReader(stream))
        freq = np.array([float(x["freq_hz"]) for x in source])
        target_db = np.array([float(x["magnitude_db"]) for x in source])
        target_phase = np.deg2rad([float(x["phase_deg"]) for x in source])
        target = 10 ** (target_db / 20) * np.exp(1j * target_phase)
        omega = 2 * np.pi * freq / row["sample_rate_hz"]
        start = np.clip(np.asarray(row["parameters"]), lower + 1e-8, upper - 1e-8)

        def residual(parameters):
            ratio = fitter.response(parameters, omega) / target
            mag_error = 20 * np.log10(np.maximum(np.abs(ratio), 1e-12))
            phase_error = np.angle(ratio) * 180 / np.pi
            return np.concatenate([mag_error, phase_error * 0.08])

        fit = least_squares(residual, start, bounds=(lower, upper), max_nfev=3000,
                            x_scale="jac", ftol=1e-9, xtol=1e-9, gtol=1e-9)
        h = fitter.response(fit.x, omega)
        mag_error = 20 * np.log10(np.abs(h)) - target_db
        phase_error = np.angle(h * np.conj(target)) * 180 / np.pi
        bands = {}
        for lo, hi in ((20, 100), (100, 1000), (1000, 18000)):
            mask = (freq >= lo) & (freq < hi if hi < 18000 else freq <= hi)
            bands[f"{lo}-{hi}"] = float(np.max(np.abs(mag_error[mask])))
        result = {"id": row["id"], "parameters": fit.x.tolist(),
                  "max_pole_radius": float(np.max(fit.x[1::4])),
                  "band_max_magnitude_error_db": bands,
                  "max_phase_error_deg": float(np.max(np.abs(phase_error))),
                  "evals": fit.nfev}
        result["pass"] = (bands["20-100"] <= .20 and bands["100-1000"] <= .15 and
                           bands["1000-18000"] <= .10 and result["max_phase_error_deg"] <= 2)
        results.append(result)
        print(f"{row['id']}: {'PASS' if result['pass'] else 'FAIL'} "
              f"pole={result['max_pole_radius']:.6f} mag={bands} "
              f"phase={result['max_phase_error_deg']:.3f} deg", flush=True)
    OUT.write_text(json.dumps({"schema": "altair-eq.pole-margin-probe/1", "max_pole_radius": MAX_RADIUS,
                               "source_fit": str(FITS.relative_to(ROOT)).replace("\\", "/"),
                               "results": results}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"summary: {sum(x['pass'] for x in results)}/{len(results)} pass")


if __name__ == "__main__":
    main()
