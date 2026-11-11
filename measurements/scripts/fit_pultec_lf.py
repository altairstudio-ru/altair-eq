#!/usr/bin/env python3
"""Fit a compact four-biquad LF model to the -36 dBFS reference sweeps."""
import csv
import json
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares
from scipy.spatial import Delaunay

ROOT = Path(__file__).resolve().parents[2]
ANALYSIS = ROOT / "measurements/results/pultec_lf/lowlevel_analysis_manifest.json"
FLAT_CSV = ROOT / "measurements/results/pultec_lf/level_sweep_control_v2/flat-m36-44k1-sweep.csv"
EXTRA_CSV = ROOT / "measurements/results/pultec_lf/level_sweep_control_v2/char60-b6-a4-m36-44k1-sweep.csv"
OUT = ROOT / "measurements/results/pultec_lf/fitted_model.json"
SR = 44100


def read_curve(path):
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    freq = np.array([float(x["freq_hz"]) for x in rows])
    mag = np.array([float(x["magnitude_db"]) for x in rows])
    phase = np.deg2rad(np.array([float(x["phase_deg"]) for x in rows]))
    return freq, mag, phase


def rbj(kind, freq, gain, shape, rate=SR):
    A = 10.0 ** (gain / 40.0)
    w = 2.0 * np.pi * freq / rate
    c, s = np.cos(w), np.sin(w)
    if kind == "peak":
        alpha = s / (2.0 * shape)
        b0, b1, b2 = 1 + alpha * A, -2 * c, 1 - alpha * A
        a0, a1, a2 = 1 + alpha / A, -2 * c, 1 - alpha / A
    else:
        S = shape
        alpha = s / 2.0 * np.sqrt((A + 1.0 / A) * (1.0 / S - 1.0) + 2.0)
        beta = 2.0 * np.sqrt(A) * alpha
        if kind == "low":
            b0 = A * ((A + 1) - (A - 1) * c + beta)
            b1 = 2 * A * ((A - 1) - (A + 1) * c)
            b2 = A * ((A + 1) - (A - 1) * c - beta)
            a0 = (A + 1) + (A - 1) * c + beta
            a1 = -2 * ((A - 1) + (A + 1) * c)
            a2 = (A + 1) + (A - 1) * c - beta
        else:
            b0 = A * ((A + 1) + (A - 1) * c + beta)
            b1 = -2 * A * ((A - 1) + (A + 1) * c)
            b2 = A * ((A + 1) + (A - 1) * c - beta)
            a0 = (A + 1) - (A - 1) * c + beta
            a1 = 2 * ((A - 1) - (A + 1) * c)
            a2 = (A + 1) - (A - 1) * c - beta
    return np.array([b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0])


KINDS = ("low", "peak", "low", "peak", "low", "peak", "low", "high")


def response(params, freq, rate=SR):
    z = np.exp(-1j * 2.0 * np.pi * freq / rate)
    h = np.ones_like(z, dtype=np.complex128)
    for i, kind in enumerate(KINDS):
        gain, logf, logshape = params[i * 3:i * 3 + 3]
        b0, b1, b2, a1, a2 = rbj(kind, np.exp(logf), gain, np.exp(logshape), rate)
        h *= (b0 + b1 * z + b2 * z * z) / (1.0 + a1 * z + a2 * z * z)
    return h


def fit_curve(freq, mag_db, phase, cps, boost, atten, phase_weight=0.08):
    target = 10.0 ** (mag_db / 20.0) * np.exp(1j * phase)
    high_base = float(np.median(mag_db[freq >= 10000]))
    low_base = float(np.mean(mag_db[freq <= max(25, cps * 0.5)]))
    low_gain = low_base - high_base
    ls = rbj("low", cps, low_gain, 0.7)
    z = np.exp(-1j * 2.0 * np.pi * freq / SR)
    hlow = (ls[0] + ls[1] * z + ls[2] * z * z) / (1.0 + ls[3] * z + ls[4] * z * z)
    residual_curve = mag_db - high_base - 20.0 * np.log10(np.maximum(np.abs(hlow), 1e-12))
    band = (freq >= cps * 0.5) & (freq <= 2000)
    band_indices = np.where(band)[0]
    pos_index = int(band_indices[np.argmax(residual_curve[band])])
    neg_index = int(band_indices[np.argmin(residual_curve[band])])
    gains = [low_gain, float(np.clip(residual_curve[pos_index], -24, 24)), 0,
             float(np.clip(residual_curve[neg_index], -24, 24)), 0, 0, 0, high_base]
    frequencies = [cps, float(freq[pos_index]), cps * 2, float(freq[neg_index]),
                   cps * 3, cps * 4, cps * 6, 8000]
    x0, lower, upper = [], [], []
    for kind, gain, f0 in zip(KINDS, gains, frequencies):
        if kind == "low":
            x0 += [gain, np.log(f0), 0.0]
            lower += [-30, np.log(8), np.log(0.2)]
            upper += [30, np.log(1500), 0.0]
        elif kind == "peak":
            x0 += [gain, np.log(f0), np.log(0.8)]
            lower += [-30, np.log(8), np.log(0.15)]
            upper += [30, np.log(6000), np.log(12)]
        else:
            x0 += [gain, np.log(f0), 0.0]
            lower += [-8, np.log(1000), np.log(0.2)]
            upper += [8, np.log(18000), 0.0]
    x0, lower, upper = np.array(x0), np.array(lower), np.array(upper)
    # Equalize phase and magnitude units; the phase weight corresponds to a
    # modest preference for respecting the approved 2-degree phase tolerance.
    def residual(p):
        h = response(p, freq)
        mag_err = 20.0 * np.log10(np.maximum(np.abs(h), 1e-12)) - mag_db
        phase_err = np.angle(h * np.conj(target)) * 180.0 / np.pi
        return np.concatenate((mag_err, phase_err * phase_weight))
    starts = [x0, x0.copy()]
    for i in range(len(KINDS)):
        starts[1][i * 3] *= 0.35
        starts[1][i * 3 + 1] = np.clip(starts[1][i * 3 + 1] + (-0.25 if i % 2 else 0.25),
                                       lower[i * 3 + 1] + 1e-5, upper[i * 3 + 1] - 1e-5)
    results = [least_squares(residual, start, bounds=(lower, upper), max_nfev=300,
                             x_scale="jac", ftol=1e-8, xtol=1e-8, gtol=1e-8)
               for start in starts]
    result = min(results, key=lambda x: x.cost)
    h = response(result.x, freq)
    mag_err = 20 * np.log10(np.maximum(np.abs(h), 1e-12)) - mag_db
    phase_err = np.angle(h * np.conj(target)) * 180.0 / np.pi
    return result.x, {
        "success": bool(result.success),
        "cost": float(result.cost),
        "max_abs_magnitude_error_db": float(np.max(np.abs(mag_err))),
        "rms_magnitude_error_db": float(np.sqrt(np.mean(mag_err ** 2))),
        "max_abs_phase_error_deg": float(np.max(np.abs(phase_err))),
        "rms_phase_error_deg": float(np.sqrt(np.mean(phase_err ** 2))),
    }


def main():
    source = json.loads(ANALYSIS.read_text(encoding="utf-8"))
    nodes = {}
    for item in source["rows"]:
        if item["sample_rate_hz"] != SR:
            continue
        p = item["configuration"]
        key = (int(p["lf_cps_hz"]), float(p["lf_boost_ui"] or 0), float(p["lf_atten_ui"] or 0))
        freq, mag, phase = read_curve(ROOT / item["analysis_csv"])
        params, error = fit_curve(freq, mag, phase, key[0], key[1], key[2])
        nodes.setdefault(key[0], []).append({"boost": key[1], "atten": key[2],
                                             "parameters": params.tolist(), "error": error,
                                             "source": item["analysis_csv"]})
        if len(nodes[key[0]]) % 10 == 0:
            print(f"fitted CPS {key[0]}: {len(nodes[key[0]])} nodes", flush=True)

    # The flat transfer is independent of CPS by design; use the direct level
    # controlled flat measurement as the neutral node at every CPS.
    freq, mag, phase = read_curve(FLAT_CSV)
    params, error = fit_curve(freq, mag, phase, 60, 0, 0)
    for cps in (20, 30, 60, 100):
        if not any(x["boost"] == 0 and x["atten"] == 0 for x in nodes[cps]):
            nodes[cps].append({"boost": 0, "atten": 0, "parameters": params.tolist(),
                               "error": error, "source": str(FLAT_CSV.relative_to(ROOT)).replace("\\", "/")})
    # Include the dedicated CPS60/B6/A4 level-control curve absent from the
    # static full grid, so its approved golden tolerance is directly tested.
    freq, mag, phase = read_curve(EXTRA_CSV)
    params, error = fit_curve(freq, mag, phase, 60, 6, 4)
    nodes[60].append({"boost": 6, "atten": 4, "parameters": params.tolist(), "error": error,
                      "source": str(EXTRA_CSV.relative_to(ROOT)).replace("\\", "/")})

    for cps, entries in nodes.items():
        points = np.array([[x["boost"], x["atten"]] for x in entries])
        triangulation = Delaunay(points)
        for entry, simplex in zip(entries, triangulation.simplices):
            entry["triangle_indices"] = [int(x) for x in simplex]
        print(f"CPS {cps}: {len(entries)} fitted nodes; worst fit {max(x['error']['max_abs_magnitude_error_db'] for x in entries):.4f} dB / {max(x['error']['max_abs_phase_error_deg'] for x in entries):.3f} deg")
    out = {"schema": "altair-eq.pultec-lf-fit/1", "sample_rate_hz": SR,
           "sections": list(KINDS),
           "parameter_layout": ["gain_db", "log_frequency_hz", "log_shape_q_or_slope"] * len(KINDS),
           "fit_method": "bounded nonlinear least squares on magnitude and wrapped phase",
           "nodes_by_cps": {str(k): v for k, v in nodes.items()}}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"fit table written: {OUT}")


if __name__ == "__main__":
    main()
