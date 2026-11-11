#!/usr/bin/env python3
"""Probe a pooled 12-pole-pair IIR denominator with per-node 24th-order FIR numerators."""
import csv
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
FIT = ROOT / "measurements/results/pultec_lf/stable_sos_six_section_fits_r0999.json"
FLAT_FIT = ROOT / "measurements/results/pultec_lf/flat_reference_fit.json"
FLAT_CSV = ROOT / "measurements/results/pultec_lf/level_sweep_control_v2/flat-m36-44k1-sweep.csv"
OUT = ROOT / "measurements/results/pultec_lf/shared_denominator24_probe.json"
SR = 44100
POLE_PAIRS = 12


def read_curve(path):
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    freq = np.array([float(row["freq_hz"]) for row in rows])
    db = np.array([float(row["magnitude_db"]) for row in rows])
    phase = np.deg2rad([float(row["phase_deg"]) for row in rows])
    return freq, 10 ** (db / 20) * np.exp(1j * phase), db


def metric(freq, target, target_db, response):
    mag = 20 * np.log10(np.maximum(np.abs(response), 1e-12)) - target_db
    phase = np.angle(response * np.conj(target)) * 180 / np.pi
    bands = {}
    for lo, hi in ((20, 100), (100, 1000), (1000, 18000)):
        mask = (freq >= lo) & (freq < hi if hi < 18000 else freq <= hi)
        bands[f"{lo}-{hi}"] = float(np.max(np.abs(mag[mask])))
    passed = bool(bands["20-100"] <= .2 and bands["100-1000"] <= .15
                  and bands["1000-18000"] <= .1 and np.max(np.abs(phase)) <= 2)
    return passed, bands, float(np.max(np.abs(phase)))


def fit_numerator(freq, target, denominator_coeffs):
    omega = 2 * np.pi * freq / SR
    q = np.exp(-1j * omega)
    den = np.ones(q.shape, dtype=np.complex128)
    for i in range(POLE_PAIRS):
        r, theta = denominator_coeffs[i]
        den *= 1 - 2 * r * np.cos(theta) * q + r * r * q * q
    matrix_c = np.column_stack([q ** k for k in range(2 * POLE_PAIRS + 1)]) / den[:, None]
    matrix = np.concatenate([matrix_c.real, matrix_c.imag], axis=0)
    vector = np.concatenate([target.real, target.imag])
    coeff, _, _, _ = np.linalg.lstsq(matrix, vector, rcond=1e-13)
    response = matrix_c @ coeff
    return coeff, response, float(np.linalg.cond(matrix))


def main():
    fit_rows = json.loads(FIT.read_text(encoding="utf-8"))["results"]
    flat_roots = json.loads(FLAT_FIT.read_text(encoding="utf-8"))["result"]["parameters"]
    results, models = [], {}
    for cps in (20, 30, 60, 100):
        family = [r for r in fit_rows if r["sample_rate_hz"] == SR
                  and r["configuration"]["lf_cps_hz"] == cps]
        sources = [(r["id"], r["configuration"], ROOT / r["source"], r["parameters"])
                   for r in family]
        sources.append(("flat", {"lf_cps_hz": cps, "lf_boost_ui": 0, "lf_atten_ui": 0},
                        FLAT_CSV, flat_roots))
        poles = []
        for _, _, _, p in sources:
            poles.extend([(float(p[1 + 4*i]), float(p[2 + 4*i])) for i in range(6)])
        poles.sort(key=lambda item: item[1])
        buckets = np.array_split(np.asarray(poles), POLE_PAIRS)
        denominator = [[float(np.median(bucket[:, 0])), float(np.median(bucket[:, 1]))]
                       for bucket in buckets]
        current = []
        for rid, config, path, _ in sources:
            freq, target, db = read_curve(path)
            numerator, h, condition = fit_numerator(freq, target, denominator)
            passed, bands, phase = metric(freq, target, db, h)
            result = {"id": rid, "sample_rate_hz": SR, **config, "pass": passed,
                      "band_max_magnitude_error_db": bands, "max_phase_error_deg": phase,
                      "numerator_condition_number": condition,
                      "numerator_coefficients": numerator.tolist()}
            current.append(result)
        models[str(cps)] = {"poles": denominator, "results": current}
        results.extend(current)
        print(f"CPS {cps}: {sum(r['pass'] for r in current)}/{len(current)}; "
              f"median cond={np.median([r['numerator_condition_number'] for r in current]):.3g}", flush=True)
    OUT.write_text(json.dumps({"schema": "altair-eq.pultec-lf-shared-denominator24/1",
                               "method": "12 pooled stable pole pairs plus per-node real FIR numerator least squares",
                               "sample_rate_hz": SR, "numerator_order": 24,
                               "models": models, "results": results}, indent=2) + "\n", encoding="utf-8")
    print(f"overall {sum(r['pass'] for r in results)}/{len(results)} -> {OUT}")


if __name__ == "__main__":
    main()
