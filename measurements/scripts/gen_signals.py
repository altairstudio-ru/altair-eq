#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Генератор измерительных сигналов (этап 3, docs/WORK_PLAN_PULTEC_MVP.md).

Спецификации сигналов совпадают с measurements/grid/pultec_lf_grid.json.
Выход: stereo 32-bit float WAV в measurements/signals/ (gitignored) и
манифест с SHA-256 в measurements/results/signals_manifest.json (коммитится).

Запуск: python measurements/scripts/gen_signals.py
"""
import hashlib
import io
import json
import os
from datetime import datetime, timezone

import numpy as np
from scipy.io import wavfile

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
SIGNAL_DIR = os.path.join(ROOT, "measurements", "signals")
MANIFEST_PATH = os.path.join(ROOT, "measurements", "results", "signals_manifest.json")

SAMPLE_RATES = [44100, 48000, 96000]
LEVEL_FREQS = [50, 100, 1000]
LEVELS_DBFS = [-36, -24, -18, -12, -6]
IMD_LEVELS_DBFS = [-12, -6]


def level_token(db):
    return "m{}".format(abs(int(db)))


def fade(signal, sr, fade_s):
    n = int(round(fade_s * sr))
    if n <= 0 or 2 * n >= len(signal):
        return signal
    ramp = 0.5 - 0.5 * np.cos(np.linspace(0.0, np.pi, n))
    signal = signal.copy()
    signal[:n] *= ramp
    signal[-n:] *= ramp[::-1]
    return signal


def stereo(signal):
    return np.column_stack([signal, signal]).astype(np.float32)


def make_impulse(sr):
    total = int(round(5.0 * sr))
    lead = int(round(0.2 * sr))
    x = np.zeros(total, dtype=np.float64)
    x[lead] = 1.0
    return x, {"lead_s": 0.2, "active_s": 0.0, "tail_s": (total - lead - 1) / sr,
               "level_dbfs": 0.0, "impulse_position_samples": lead}


def make_sweep_log(sr):
    f1, f2, T = 1.0, 0.45 * sr, 15.0
    lead_s, tail_s = 0.5, 2.0
    n_lead, n_sweep, n_tail = int(round(lead_s * sr)), int(round(T * sr)), int(round(tail_s * sr))
    t = np.arange(n_sweep) / sr
    L = T / np.log(f2 / f1)
    # Farina log sweep: instantaneous frequency f1*exp(t/L).
    phase = 2.0 * np.pi * f1 * L * (np.exp(t / L) - 1.0)
    sweep = np.sin(phase) * (10.0 ** (-12.0 / 20.0))
    sweep = fade(sweep, sr, 0.05)
    x = np.concatenate([np.zeros(n_lead), sweep, np.zeros(n_tail)])
    return x, {"lead_s": lead_s, "active_s": T, "tail_s": tail_s, "level_dbfs": -12.0,
               "f_start_hz": f1, "f_end_hz": f2, "fade_s": 0.05}


def make_sine(sr, freq, level_db):
    T = 10.0
    n = int(round(T * sr))
    t = np.arange(n) / sr
    x = np.sin(2.0 * np.pi * freq * t) * (10.0 ** (level_db / 20.0))
    x = fade(x, sr, 0.01)
    return x, {"active_s": T, "lead_s": 0.0, "tail_s": 0.0, "level_dbfs": level_db,
               "frequency_hz": freq, "fade_s": 0.01}


def make_twotone(sr, level_db):
    T = 10.0
    n = int(round(T * sr))
    t = np.arange(n) / sr
    amp = 10.0 ** (level_db / 20.0)
    x = (0.8 * np.sin(2.0 * np.pi * 50.0 * t) + 0.2 * np.sin(2.0 * np.pi * 1000.0 * t)) * amp
    x = fade(x, sr, 0.01)
    return x, {"active_s": T, "lead_s": 0.0, "tail_s": 0.0, "level_dbfs": level_db,
               "frequencies_hz": [50.0, 1000.0], "amplitude_ratio": "4:1", "fade_s": 0.01,
               "note": "0.8/0.2 split keeps worst-case peak at the stated level"}


def write_wav(name, sr, signal, meta, entries):
    os.makedirs(SIGNAL_DIR, exist_ok=True)
    path = os.path.join(SIGNAL_DIR, name)
    data = stereo(signal)
    wavfile.write(path, sr, data)
    with io.open(path, "rb") as handle:
        sha = hashlib.sha256(handle.read()).hexdigest()
    entries.append({
        "file": "measurements/signals/" + name,
        "sha256": sha,
        "sample_rate_hz": sr,
        "samples": int(data.shape[0]),
        "channels": 2,
        "format": "wav_float32",
        "duration_total_s": data.shape[0] / sr,
        "peak_abs": float(np.max(np.abs(data))),
        **meta,
    })


def main():
    entries = []
    for sr in SAMPLE_RATES:
        x, meta = make_impulse(sr)
        write_wav("impulse-{}.wav".format(sr), sr, x, {"type": "impulse", **meta}, entries)
        x, meta = make_sweep_log(sr)
        write_wav("sweep_log-{}.wav".format(sr), sr, x, {"type": "log_sweep", **meta}, entries)
        for freq in LEVEL_FREQS:
            for level in LEVELS_DBFS:
                x, meta = make_sine(sr, freq, level)
                write_wav("sine_{}_{}-{}.wav".format(freq, level_token(level), sr), sr, x,
                          {"type": "sine", **meta}, entries)
        for level in IMD_LEVELS_DBFS:
            x, meta = make_twotone(sr, level)
            write_wav("twotone_50_1000_{}-{}.wav".format(level_token(level), sr), sr, x,
                      {"type": "two_tone", **meta}, entries)

    manifest = {
        "schema": "altair-eq.signals-manifest/1",
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generator": "measurements/scripts/gen_signals.py",
        "grid_ref": "measurements/grid/pultec_lf_grid.json",
        "file_count": len(entries),
        "files": entries,
    }
    os.makedirs(os.path.dirname(MANIFEST_PATH), exist_ok=True)
    with io.open(MANIFEST_PATH, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print("Signals written: {} files -> {}".format(len(entries), SIGNAL_DIR))
    print("Manifest: " + MANIFEST_PATH)


if __name__ == "__main__":
    main()