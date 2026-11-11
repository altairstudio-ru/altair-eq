#!/usr/bin/env python3
"""Fit compact stable SOS to residual SVD modes using complex absolute error."""
import csv
import json
import argparse
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares

ROOT = Path(__file__).resolve().parents[2]
MODE_DIR = ROOT / "measurements/results/pultec_lf/joint_residual_svd_modes"
OUT = ROOT / "measurements/results/pultec_lf/joint_residual_svd_mode_complex_fits.json"
SR, SECTIONS, STARTS, MAX_NFEV = 44100, 12, 3, 2400
MAX_RADIUS = .999


def load_curve(path):
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    freq = np.array([float(row["freq_hz"]) for row in rows])
    mag = 10 ** (np.array([float(row["magnitude_db"]) for row in rows]) / 20)
    phase = np.deg2rad([float(row["phase_deg"]) for row in rows])
    return freq, mag * np.exp(1j * phase)


def response(parameters, omega):
    q = np.exp(-1j * omega)
    h = np.full(q.shape, np.exp(parameters[0]), dtype=np.complex128)
    for index in range(SECTIONS):
        rp, tp, rz, tz = parameters[1 + index * 4: 5 + index * 4]
        den = 1 - 2 * rp * np.cos(tp) * q + rp * rp * q * q
        num = 1 - 2 * rz * np.cos(tz) * q + rz * rz * q * q
        h *= num / den
    return h


def main():
    global SECTIONS, MAX_NFEV
    parser = argparse.ArgumentParser()
    parser.add_argument("--sections", type=int, default=SECTIONS)
    parser.add_argument("--max-nfev", type=int, default=MAX_NFEV)
    parser.add_argument("--cps", type=int, nargs="*", default=[20, 30, 60, 100])
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    SECTIONS = args.sections
    MAX_NFEV = args.max_nfev
    output_path = args.output if args.output.is_absolute() else ROOT / args.output
    lower = np.array([-16.0] + [0.01, 1e-5, 0.01, 1e-5] * SECTIONS)
    upper = np.array([16.0] + [MAX_RADIUS, np.pi, 5.0, np.pi] * SECTIONS)
    output = []
    seed_counter = 0
    for cps in args.cps:
        manifest = json.loads((MODE_DIR / f"cps{cps}-modes.json").read_text(encoding="utf-8"))
        for row in manifest["modes"]:
            freq, target = load_curve(ROOT / row["source"])
            omega = 2 * np.pi * freq / SR
            scale = float(np.sqrt(np.mean(np.abs(target) ** 2)))
            if scale < 1e-12:
                raise SystemExit(f"degenerate mode {row['id']}")

            def residual(parameters):
                delta = (response(parameters, omega) - target) / scale
                return np.concatenate([delta.real, delta.imag])

            best = None
            centers = np.geomspace(24, SR * .27, SECTIONS)
            for start_index in range(STARTS):
                seed_counter += 1
                rng = np.random.default_rng(20261111 + cps * 100 + seed_counter * 7919)
                values = [float(np.log(max(scale, 1e-8)))]
                for center in centers:
                    angle = 2 * np.pi * center / SR
                    rp = rng.uniform(.86, .995)
                    rz = np.clip(rp + rng.normal(0, .025), .75, 1.2)
                    tp = np.clip(angle * rng.uniform(.75, 1.3), 1e-4, np.pi - 1e-4)
                    tz = np.clip(angle * rng.uniform(.75, 1.3), 1e-4, np.pi - 1e-4)
                    values.extend([rp, tp, rz, tz])
                start = np.clip(values, lower + 1e-8, upper - 1e-8)
                fit = least_squares(residual, start, bounds=(lower, upper), max_nfev=MAX_NFEV,
                                    x_scale="jac", ftol=1e-9, xtol=1e-9, gtol=1e-9)
                score = float(np.dot(fit.fun, fit.fun))
                print(f"{row['id']} start {start_index + 1}/{STARTS} cost={score:.6g} "
                      f"evals={fit.nfev}", flush=True)
                if best is None or score < best[0]:
                    best = (score, fit.x)
            predicted = response(best[1], omega)
            error = predicted - target
            item = {**row, "sample_rate_hz": SR, "sections": SECTIONS,
                    "parameters": best[1].tolist(), "normalized_complex_rms": float(np.sqrt(np.mean(np.abs(error) ** 2)) / scale),
                    "max_pole_radius": float(max(best[1][1::4])),
                    "max_abs_error": float(np.max(np.abs(error))),
                    "fit_cost": best[0], "fit_limits": {"starts": STARTS, "max_nfev": MAX_NFEV}}
            output.append(item)
            output_path.write_text(json.dumps({"schema": "altair-eq.pultec-lf-residual-mode-complex-fits/1",
                                               "sections": SECTIONS,
                                               "results": output}, ensure_ascii=False, indent=2) + "\n",
                                   encoding="utf-8")
            print(f"  normalized complex RMS={item['normalized_complex_rms']:.6g}; "
                  f"max |error|={item['max_abs_error']:.6g}", flush=True)


if __name__ == "__main__":
    main()
