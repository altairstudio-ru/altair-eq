#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Анализатор измерительных рендеров (этап 3, docs/WORK_PLAN_PULTEC_MVP.md).

Режимы:
  null     <a.wav> <b.wav> <out.json>                 — null-тест / повторяемость
  latency  <input.wav> <render.wav> <out.json>        — задержка кросс-корреляцией
  transfer <input.wav> <render.wav> <out.json> [...]  — АЧХ/фаза/group delay

transfer: H = FFT(out)/FFT(in) (Wiener-регуляризация для sweep), компенсация
задержки --latency N (целые сэмплы, измеренные режимом latency по импульсу).
--rbj F0 GAIN_DB Q включает независимую аналитическую RBJ peaking-АЧХ и гейт
по --max-err-db / --max-err-phase в полосе --fmin..--fmax.

Запуск: python measurements/scripts/analyze.py <mode> ...
"""
import argparse
import hashlib
import io
import json
import os
from datetime import datetime, timezone

import numpy as np
from scipy.io import wavfile
from scipy.signal import correlate, correlation_lags

CONTROL_FREQS = [20.0, 30.0, 50.0, 60.0, 100.0, 1000.0, 10000.0, 18000.0]


def sha256(path):
    with io.open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def load(path):
    sr, data = wavfile.read(path)
    if data.ndim != 2 or data.shape[1] != 2:
        raise SystemExit("expected stereo WAV: " + path)
    raw = data
    x = data.astype(np.float64)
    stereo_diff = float(np.max(np.abs(x[:, 0] - x[:, 1])))
    return sr, raw, x, stereo_diff


def write_json(path, obj):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(obj, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def base_report(mode, paths):
    return {
        "schema": "altair-eq.analysis/1",
        "mode": mode,
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "inputs": {p: sha256(p) for p in paths},
    }


def cmd_null(args):
    sr_a, raw_a, a, sd_a = load(args.a)
    sr_b, raw_b, b, sd_b = load(args.b)
    if sr_a != sr_b or a.shape != b.shape:
        raise SystemExit("null: sample rate or length mismatch")
    diff = a - b
    report = base_report("null", [args.a, args.b])
    report.update({
        "sample_rate_hz": sr_a,
        "samples": int(a.shape[0]),
        "bit_identical_samples": bool(np.array_equal(raw_a, raw_b)),
        "difference_peak": float(np.max(np.abs(diff))),
        "difference_rms": float(np.sqrt(np.mean(diff ** 2))),
        "stereo_difference_peak_a": sd_a,
        "stereo_difference_peak_b": sd_b,
    })
    write_json(args.out, report)
    print("null: peak={:.3e} rms={:.3e} bit_identical={}".format(
        report["difference_peak"], report["difference_rms"], report["bit_identical_samples"]))


def cmd_latency(args):
    sr, _, x, _ = load(args.input)
    sr2, _, y, sd = load(args.render)
    if sr != sr2 or x.shape != y.shape:
        raise SystemExit("latency: sample rate or length mismatch")
    xc = x[:, 0]
    yc = y[:, 0]
    corr = correlate(yc, xc, mode="full", method="fft")
    lags = correlation_lags(len(yc), len(xc), mode="full")
    lag = int(lags[int(np.argmax(np.abs(corr)))])
    report = base_report("latency", [args.input, args.render])
    report.update({
        "sample_rate_hz": sr,
        "samples": int(x.shape[0]),
        "latency_samples": lag,
        "latency_ms": lag / sr * 1000.0,
        "input_peak_position": int(np.argmax(np.abs(xc))),
        "render_peak_position": int(np.argmax(np.abs(yc))),
        "peak_shift_samples": int(np.argmax(np.abs(yc))) - int(np.argmax(np.abs(xc))),
        "stereo_difference_peak": sd,
    })
    write_json(args.out, report)
    print("latency: {} samples ({:.4f} ms), peak shift {}".format(
        lag, report["latency_ms"], report["peak_shift_samples"]))


def rbj_response(freqs, sr, f0, gain_db, q):
    A = 10.0 ** (gain_db / 40.0)
    w0 = 2.0 * np.pi * f0 / sr
    alpha = np.sin(w0) / (2.0 * q)
    cw = np.cos(w0)
    a0 = 1.0 + alpha / A
    b0, b1, b2 = (1.0 + alpha * A) / a0, (-2.0 * cw) / a0, (1.0 - alpha * A) / a0
    a1, a2 = (-2.0 * cw) / a0, (1.0 - alpha / A) / a0
    z = np.exp(-1j * 2.0 * np.pi * freqs / sr)
    return (b0 + b1 * z + b2 * z ** 2) / (1.0 + a1 * z + a2 * z ** 2)


def cmd_transfer(args):
    sr, _, x, sd_in = load(args.input)
    sr2, _, y, sd_out = load(args.render)
    if sr != sr2 or x.shape != y.shape:
        raise SystemExit("transfer: sample rate or length mismatch")
    xc, yc = x[:, 0], y[:, 0]
    n = len(xc)
    X = np.fft.rfft(xc)
    Y = np.fft.rfft(yc)
    freqs = np.fft.rfftfreq(n, 1.0 / sr)
    power = np.abs(X) ** 2
    pmax = float(np.max(power))
    eps = 1e-12 * pmax
    H = Y * np.conj(X) / (power + eps)
    latency = args.latency if args.latency is not None else 0
    if latency:
        H = H * np.exp(1j * 2.0 * np.pi * freqs * latency / sr)
    mag_db = 20.0 * np.log10(np.abs(H) + 1e-30)
    phase = np.unwrap(np.angle(H))
    omega = 2.0 * np.pi * freqs / sr
    gd_samples = np.zeros_like(freqs)
    gd_samples[1:-1] = -(phase[2:] - phase[:-2]) / (omega[2:] - omega[:-2])
    band = (freqs >= args.fmin) & (freqs <= args.fmax)
    energy = power > (1e-8 * pmax)
    mask = band & energy

    report = base_report("transfer", [args.input, args.render])
    report.update({
        "sample_rate_hz": sr,
        "samples": n,
        "latency_compensated_samples": int(latency),
        "fmin_hz": args.fmin,
        "fmax_hz": args.fmax,
        "stereo_difference_peak_input": sd_in,
        "stereo_difference_peak_render": sd_out,
        "in_band_bins": int(np.sum(mask)),
    })

    if args.rbj:
        f0, gain_db, q = args.rbj
        Ha = rbj_response(freqs, sr, f0, gain_db, q)
        mag_a = 20.0 * np.log10(np.abs(Ha))
        err_db = mag_db - mag_a
        err_phase = np.angle(H * np.conj(Ha)) * 180.0 / np.pi
        max_err_db = float(np.max(np.abs(err_db[mask])))
        max_err_phase = float(np.max(np.abs(err_phase[mask])))
        gate_pass = bool(max_err_db <= args.max_err_db and max_err_phase <= args.max_err_phase)
        report.update({
            "analytic_rbj": {"f0_hz": f0, "gain_db": gain_db, "q": q},
            "tolerance_db": args.max_err_db,
            "tolerance_phase_deg": args.max_err_phase,
            "max_error_db": max_err_db,
            "max_error_phase_deg": max_err_phase,
            "gate_pass": gate_pass,
        })
        print("transfer vs RBJ: max|err|={:.5f} dB, {:.5f} deg -> {}".format(
            max_err_db, max_err_phase, "PASS" if gate_pass else "FAIL"))
    else:
        print("transfer: {} in-band bins, latency compensated {} samples".format(
            int(np.sum(mask)), latency))

    grid = np.unique(np.concatenate([
        np.geomspace(max(args.fmin, 1.0), args.fmax, 240),
        np.array([f for f in CONTROL_FREQS if args.fmin <= f <= args.fmax]),
    ]))
    mag_g = np.interp(grid, freqs, mag_db)
    phase_g = np.interp(grid, freqs, phase)
    gd_g = np.interp(grid, freqs, gd_samples) / sr * 1000.0
    report["control_points"] = [
        {"freq_hz": float(f),
         "magnitude_db": float(np.interp(f, freqs, mag_db)),
         "phase_deg": float(np.interp(f, freqs, phase) * 180.0 / np.pi),
         "group_delay_ms": float(np.interp(f, freqs, gd_samples) / sr * 1000.0)}
        for f in CONTROL_FREQS if args.fmin <= f <= args.fmax and f <= sr / 2.0
    ]
    write_json(args.out, report)

    if args.csv:
        os.makedirs(os.path.dirname(os.path.abspath(args.csv)), exist_ok=True)
        with io.open(args.csv, "w", encoding="utf-8", newline="") as handle:
            handle.write("freq_hz,magnitude_db,phase_deg,group_delay_ms")
            if args.rbj:
                handle.write(",analytic_mag_db,analytic_phase_deg,err_db,err_phase_deg")
            handle.write("\n")
            if args.rbj:
                Ha_g = rbj_response(grid, sr, *args.rbj)
                mag_ag = 20.0 * np.log10(np.abs(Ha_g))
                phase_ag = np.unwrap(np.angle(Ha_g))
                err_db_g = mag_g - mag_ag
                err_ph_g = np.angle(np.exp(1j * (phase_g - phase_ag))) * 180.0 / np.pi
            for i, f in enumerate(grid):
                row = "{:.6f},{:.6f},{:.6f},{:.6f}".format(f, mag_g[i], phase_g[i] * 180.0 / np.pi, gd_g[i])
                if args.rbj:
                    row += ",{:.6f},{:.6f},{:.6f},{:.6f}".format(
                        mag_ag[i], phase_ag[i] * 180.0 / np.pi, err_db_g[i], err_ph_g[i])
                handle.write(row + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)

    p = sub.add_parser("null")
    p.add_argument("a")
    p.add_argument("b")
    p.add_argument("out")
    p.set_defaults(func=cmd_null)

    p = sub.add_parser("latency")
    p.add_argument("input")
    p.add_argument("render")
    p.add_argument("out")
    p.set_defaults(func=cmd_latency)

    p = sub.add_parser("transfer")
    p.add_argument("input")
    p.add_argument("render")
    p.add_argument("out")
    p.add_argument("--latency", type=int, default=None)
    p.add_argument("--rbj", type=float, nargs=3, metavar=("F0", "GAIN_DB", "Q"))
    p.add_argument("--fmin", type=float, default=20.0)
    p.add_argument("--fmax", type=float, default=18000.0)
    p.add_argument("--max-err-db", type=float, default=0.05)
    p.add_argument("--max-err-phase", type=float, default=1.0)
    p.add_argument("--csv")
    p.set_defaults(func=cmd_transfer)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()