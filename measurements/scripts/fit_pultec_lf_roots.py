#!/usr/bin/env python3
"""Fit stable SOS models to measured LF sweeps using complex frequency LS."""
import csv
from pathlib import Path

import numpy as np
from scipy.signal import sosfreqz, tf2zpk, zpk2sos


def read_curve(path):
    with Path(path).open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    freq = np.array([float(x["freq_hz"]) for x in rows])
    mag = np.array([float(x["magnitude_db"]) for x in rows])
    phase = np.deg2rad(np.array([float(x["phase_deg"]) for x in rows]))
    return freq, 10 ** (mag / 20) * np.exp(1j * phase), mag, phase


def fit(freq, target, order=8):
    q = np.exp(-1j * 2.0 * np.pi * freq / 44100.0)
    columns = [q ** k for k in range(order + 1)]
    columns += [-target * q ** k for k in range(1, order + 1)]
    A = np.column_stack(columns)
    y = target
    Ar = np.vstack((A.real, A.imag))
    yr = np.concatenate((y.real, y.imag))
    solution, *_ = np.linalg.lstsq(Ar, yr, rcond=None)
    b = solution[:order + 1]
    a = np.concatenate(([1.0], solution[order + 1:]))
    z, p, k = tf2zpk(b, a)
    p = np.array([pole if abs(pole) < 0.9999 else 0.9999 / np.conj(pole) for pole in p])
    z = np.array([zero if abs(zero) < 0.9999 else 0.9999 / np.conj(zero) for zero in z])
    sos = zpk2sos(z, p, k)
    _, h = sosfreqz(sos, worN=2.0 * np.pi * freq / 44100.0)
    return sos, h, {"max_pole_radius_before_stabilize": float(np.max(np.abs(tf2zpk(b, a)[1]))),
                    "max_pole_radius_after_stabilize": float(np.max(np.abs(p))),
                    "max_zero_radius_after_stabilize": float(np.max(np.abs(z)))}


def errors(target, h):
    dm = 20 * np.log10(np.maximum(np.abs(h), 1e-12)) - 20 * np.log10(np.maximum(np.abs(target), 1e-12))
    dp = np.angle(h * np.conj(target)) * 180 / np.pi
    return {"max_abs_magnitude_error_db": float(np.max(np.abs(dm))),
            "rms_magnitude_error_db": float(np.sqrt(np.mean(dm ** 2))),
            "max_abs_phase_error_deg": float(np.max(np.abs(dp))),
            "rms_phase_error_deg": float(np.sqrt(np.mean(dp ** 2)))}


if __name__ == "__main__":
    path = Path("measurements/results/pultec_lf/lowlevel_transfer/boost_atten_trick-30-b080-a080-44k1-swp-m36.csv")
    f, target, _, _ = read_curve(path)
    for order in (4, 6, 8, 10, 12):
        sos, h, radii = fit(f, target, order)
        print(order, errors(target, h), radii)
