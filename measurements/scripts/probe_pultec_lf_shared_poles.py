#!/usr/bin/env python3
"""Probe a causal shared-pole IIR/FIR architecture against measured LF curves."""
import csv
import json
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares

ROOT = Path(__file__).resolve().parents[2]
FIT_PATH = ROOT / "measurements/results/pultec_lf/stable_sos_six_section_fits_r0999.json"
FLAT_PATH = ROOT / "measurements/results/pultec_lf/flat_reference_fit.json"
FLAT_CSV = ROOT / "measurements/results/pultec_lf/level_sweep_control_v2/flat-m36-44k1-sweep.csv"
OUT = ROOT / "measurements/results/pultec_lf/shared_poles_probe.json"
SR = 44100
SECTIONS = 6


def target(path):
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    f = np.array([float(row["freq_hz"]) for row in rows])
    db = np.array([float(row["magnitude_db"]) for row in rows])
    phase = np.deg2rad([float(row["phase_deg"]) for row in rows])
    return f, 10 ** (db / 20) * np.exp(1j * phase), db, phase


def denominator_response(parameters, omega):
    q = np.exp(-1j * omega)
    a = np.ones(q.shape, dtype=np.complex128)
    for i in range(SECTIONS):
        rp, tp = parameters[1 + i * 4: 3 + i * 4]
        a *= 1 - 2 * rp * np.cos(tp) * q + rp * rp * q * q
    return a


def metrics(freq, target_h, target_db, target_phase, h):
    mag = 20 * np.log10(np.maximum(np.abs(h), 1e-12)) - target_db
    phase = np.angle(h * np.conj(target_h)) * 180 / np.pi
    upper = min(18000, SR / 2)
    bands = {}
    for lo, hi in ((20, 100), (100, 1000), (1000, upper)):
        mask = (freq >= lo) & (freq < hi if hi < 18000 else freq <= hi)
        bands[f"{lo}-{hi:g}"] = float(np.max(np.abs(mag[mask])))
    passed = bool(bands["20-100"] <= .20 and bands["100-1000"] <= .15
                  and bands[f"1000-{upper:g}"] <= .10 and np.max(np.abs(phase)) <= 2)
    return passed, bands, float(np.max(np.abs(phase)))


def fit_numerator(desired, omega, order):
    q = np.exp(-1j * omega)
    design = np.column_stack([q ** k for k in range(order + 1)])
    matrix = np.concatenate([design.real, design.imag], axis=0)
    vector = np.concatenate([desired.real, desired.imag])
    coeff, _, _, _ = np.linalg.lstsq(matrix, vector, rcond=1e-12)
    return coeff, float(np.linalg.cond(matrix))


def fit_shared(candidates, pole_seed):
    """Variable-projection fit: optimize stable shared poles, solve each FIR numerator exactly."""
    prepared = []
    for rid, config, path in candidates:
        freq, h, db, ph = target(path)
        omega = 2 * np.pi * freq / SR
        prepared.append((rid, config, freq, omega, h, db, ph))

    def projected(pole_parameters, collect=False):
        pole_vector = [0.0]
        for radius, angle in pole_parameters.reshape(SECTIONS, 2):
            pole_vector.extend([radius, angle, 1.0, 0.0])
        residuals, outputs = [], []
        for rid, config, freq, omega, h, db, ph in prepared:
            a = denominator_response(pole_vector, omega)
            q = np.exp(-1j * omega)
            design = np.column_stack([q ** k for k in range(2 * SECTIONS + 1)]) / a[:, None]
            matrix = np.concatenate([design.real, design.imag], axis=0)
            vector = np.concatenate([h.real, h.imag])
            coeff, _, _, _ = np.linalg.lstsq(matrix, vector, rcond=1e-12)
            response = np.sum(design * coeff[None, :], axis=1)
            if collect:
                passed, bands, phase_error = metrics(freq, h, db, ph, response)
                outputs.append({"id": rid, "sample_rate_hz": SR, **config, "pass": passed,
                                "band_max_magnitude_error_db": bands,
                                "max_phase_error_deg": phase_error,
                                "numerator_condition_number": float(np.linalg.cond(matrix)),
                                "numerator_coefficients": coeff.tolist()})
            else:
                mag_error = 20 * np.log10(np.maximum(np.abs(response), 1e-12)) - db
                phase_error = np.angle(response * np.conj(h))
                residuals.extend(mag_error.tolist())
                residuals.extend((phase_error * 180 / np.pi * .08).tolist())
        return (np.asarray(residuals), outputs) if collect else np.asarray(residuals)

    seed = np.asarray(pole_seed, dtype=float).reshape(-1)
    lower = np.tile([.80, 1e-5], SECTIONS)
    upper = np.tile([.9995, np.pi], SECTIONS)
    optimized = least_squares(lambda p: projected(p), seed, bounds=(lower, upper),
                              max_nfev=160, x_scale="jac", ftol=1e-6,
                              xtol=1e-6, gtol=1e-6, verbose=0)
    _, outputs = projected(optimized.x, collect=True)
    return optimized, outputs


def main():
    fits = json.loads(FIT_PATH.read_text(encoding="utf-8"))["results"]
    flat = json.loads(FLAT_PATH.read_text(encoding="utf-8"))["result"]["parameters"]
    rows = []
    for cps in (20, 30, 60, 100):
        family = [r for r in fits if r["sample_rate_hz"] == SR
                  and r["configuration"]["lf_cps_hz"] == cps]
        # Align poles by angular order, then use the median stable radius and angle.
        pole_rows = []
        for row in family + [{"parameters": flat}]:
            p = row["parameters"]
            poles = sorted([(p[1 + i * 4], p[2 + i * 4]) for i in range(SECTIONS)], key=lambda x: x[1])
            pole_rows.append(poles)
        poles = [(float(np.median([r[i][0] for r in pole_rows])),
                  float(np.median([r[i][1] for r in pole_rows]))) for i in range(SECTIONS)]
        denominator = [0.0]
        for radius, angle in poles:
            denominator.extend([-2 * radius * np.cos(angle), radius * radius])
        targets = [(r["id"], r["configuration"], ROOT / r["source"]) for r in family]
        targets.append(("flat", {"lf_cps_hz": cps, "lf_boost_ui": 0, "lf_atten_ui": 0}, FLAT_CSV))
        optimized, projected_rows = fit_shared(targets, poles)
        fitted_poles = optimized.x.reshape(SECTIONS, 2).tolist()
        for row in projected_rows:
            row["shared_poles"] = fitted_poles
            row["optimizer_cost"] = float(optimized.cost)
            row["optimizer_evaluations"] = int(optimized.nfev)
        rows.extend(projected_rows)
        current = [r for r in rows if r.get("lf_cps_hz") == cps]
        print(f"CPS {cps}: {sum(r['pass'] for r in current)}/{len(current)}; "
              f"optimizer evals={optimized.nfev}, cost={optimized.cost:.4g}", flush=True)
    OUT.write_text(json.dumps({"schema": "altair-eq.pultec-lf-shared-poles-probe/1",
                               "method": "per-CPS optimized shared stable denominator, per-node real FIR numerator variable projection",
                               "sample_rate_hz": SR, "numerator_order": 12,
                               "results": rows}, indent=2) + "\n", encoding="utf-8")
    print(f"overall {sum(r['pass'] for r in rows)}/{len(rows)} -> {OUT}")


if __name__ == "__main__":
    main()
