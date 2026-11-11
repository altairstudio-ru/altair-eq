#!/usr/bin/env python3
"""Fit stable four-biquad models to measured Pultec LF transfer curves."""
import csv
import json
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "measurements/results/pultec_lf/lowlevel_analysis_manifest.json"
OUT = ROOT / "measurements/results/pultec_lf/stable_sos_fits.json"
SECTIONS = 4
MAX_POLE_RADIUS = 0.9999


def read_target(path):
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    freq = np.array([float(row["freq_hz"]) for row in rows])
    magnitude = np.array([float(row["magnitude_db"]) for row in rows])
    phase = np.deg2rad([float(row["phase_deg"]) for row in rows])
    return freq, 10 ** (magnitude / 20) * np.exp(1j * phase), magnitude, phase


def response(parameters, omega):
    gain = np.exp(parameters[0])
    q = np.exp(-1j * omega)
    h = np.full(q.shape, gain, dtype=np.complex128)
    for index in range(SECTIONS):
        rp, tp, rz, tz = parameters[1 + index * 4: 5 + index * 4]
        denominator = 1 - 2 * rp * np.cos(tp) * q + rp * rp * q * q
        numerator = 1 - 2 * rz * np.cos(tz) * q + rz * rz * q * q
        h *= numerator / denominator
    return h


def fit_curve(path, sr, seed, warm_start=None, max_starts=3, max_nfev=1200):
    freq, target, target_db, _ = read_target(path)
    omega = 2 * np.pi * freq / sr
    lower = np.array([-12.0] + [0.01, 1e-5, 0.01, 1e-5] * SECTIONS)
    upper = np.array([12.0] + [MAX_POLE_RADIUS, np.pi, 5.0, np.pi] * SECTIONS)
    starts = []
    centers = np.geomspace(24, sr * 0.27, SECTIONS)
    for start_index in range(max_starts):
        rng = np.random.default_rng(seed + start_index * 104729 + 20261110)
        values = [float(np.median(target_db[:10]) * 0.115)]
        for center in centers:
            angle = 2 * np.pi * center / sr
            rp = rng.uniform(0.86, 0.995)
            rz = np.clip(rp + rng.normal(0, 0.025), 0.75, 1.2)
            tp = np.clip(angle * rng.uniform(0.75, 1.3), 1e-4, np.pi - 1e-4)
            tz = np.clip(angle * rng.uniform(0.75, 1.3), 1e-4, np.pi - 1e-4)
            values.extend([rp, tp, rz, tz])
        starts.append(np.clip(values, lower + 1e-8, upper - 1e-8))
    if warm_start is not None:
        warm = list(warm_start)
        while len(warm) < len(lower):
            warm.extend([0.9, 0.2, 0.9, 0.2])
        starts[0] = np.clip(np.asarray(warm[:len(lower)]), lower + 1e-8, upper - 1e-8)

    def residual(parameters):
        h = response(parameters, omega)
        ratio = h / target
        magnitude_error = 20 * np.log10(np.maximum(np.abs(ratio), 1e-12))
        phase_error = np.angle(ratio) * 180 / np.pi
        return np.concatenate([magnitude_error, phase_error * 0.08])

    best = None
    for index, start in enumerate(starts, 1):
        result = least_squares(residual, start, bounds=(lower, upper), max_nfev=max_nfev,
                               x_scale="jac", ftol=1e-9, xtol=1e-9, gtol=1e-9)
        score = float(np.dot(result.fun, result.fun))
        if best is None or score < best[0]:
            best = (score, result.x)
        print(f"  {'warm' if index == 1 and warm_start is not None else 'start'} {index}/3 cost={score:.6g} evals={result.nfev}", flush=True)

    parameters = best[1]
    h = response(parameters, omega)
    mag_error = 20 * np.log10(np.abs(h)) - target_db
    phase_error = np.angle(h * np.conj(target)) * 180 / np.pi
    band_errors = {}
    for lower_hz, upper_hz, tolerance in ((20, 100, 0.20), (100, 1000, 0.15), (1000, min(18000, sr / 2), 0.10)):
        band = (freq >= lower_hz) & (freq < upper_hz if upper_hz < 18000 else freq <= upper_hz)
        band_errors[f"{lower_hz}-{upper_hz}"] = float(np.max(np.abs(mag_error[band])))
    poles = [float(value) for value in parameters[1::4]]
    return {
        "parameters": parameters.tolist(),
        "max_pole_radius": max(poles),
        "rms_magnitude_error_db": float(np.sqrt(np.mean(mag_error ** 2))),
        "band_max_magnitude_error_db": band_errors,
        "max_phase_error_deg": float(np.max(np.abs(phase_error))),
        "rms_phase_error_deg": float(np.sqrt(np.mean(phase_error ** 2))),
        "worst_magnitude_frequency_hz": float(freq[int(np.argmax(np.abs(mag_error)))]),
    }


def run():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if OUT.exists():
        saved = json.loads(OUT.read_text(encoding="utf-8"))
        if saved.get("manifest") != str(MANIFEST.relative_to(ROOT)).replace("\\", "/"):
            raise SystemExit("saved fit set belongs to a different analysis manifest")
        results = saved.get("results", [])
    else:
        results = []
    results_by_id = {row["id"]: row for row in results}
    done = {row["id"] for row in results if row.get("method_version") == 3}
    previous_by_family = {}
    for index, row in enumerate(manifest["rows"], 1):
        sample_rate = int(row["sample_rate_hz"])
        parts = row["id"].split("-")
        family = (sample_rate, parts[0], parts[1])
        if row["id"] in done:
            print(f"[{index}/{len(manifest['rows'])}] already fitted {row['id']}", flush=True)
            previous_by_family[family] = results_by_id[row["id"]]["parameters"]
            continue
        source = ROOT / row["analysis_csv"]
        print(f"[{index}/{len(manifest['rows'])}] {row['id']}", flush=True)
        fit = fit_curve(source, sample_rate, index * 7919, previous_by_family.get(family))
        fit.update({"id": row["id"], "sample_rate_hz": sample_rate,
                    "configuration": row["configuration"], "source": row["analysis_csv"],
                    "method_version": 3})
        tolerances = {"20-100": 0.20, "100-1000": 0.15}
        tolerances[f"1000-{min(18000, sample_rate / 2):g}"] = 0.10
        fit["pass"] = (fit["max_pole_radius"] < 1.0 and fit["max_phase_error_deg"] <= 2.0 and
                       all(fit["band_max_magnitude_error_db"][band] <= limit for band, limit in tolerances.items()))
        results_by_id[row["id"]] = fit
        previous_by_family[family] = fit["parameters"]
        results = [results_by_id[key] for key in results_by_id]
        print(f"  {'PASS' if fit['pass'] else 'FAIL'} mag={fit['band_max_magnitude_error_db']} phase={fit['max_phase_error_deg']:.3f} deg", flush=True)
        OUT.write_text(json.dumps({"schema": "altair-eq.stable-sos-fit/1", "sections": SECTIONS,
                                   "method": "bounded nonlinear fit of four stable biquads to complex transfer with adjacent-node warm starts",
                                   "manifest": str(MANIFEST.relative_to(ROOT)).replace("\\", "/"),
                                   "results": results}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"summary: {sum(bool(row['pass']) for row in results)}/{len(results)} pass -> {OUT}")


if __name__ == "__main__":
    run()
