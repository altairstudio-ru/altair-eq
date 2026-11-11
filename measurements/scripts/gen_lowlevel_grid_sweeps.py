#!/usr/bin/env python3
"""Generate -36 dBFS log sweeps for the 44.1/48/96 kHz reference grid."""
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.io import wavfile

ROOT = Path(__file__).resolve().parents[2]
SIGNAL_DIR = ROOT / "measurements/signals"
RATES = (44100, 48000, 96000)
LEVEL_DBFS = -36


def create(sr):
    f1, f2, duration = 1.0, 0.45 * sr, 15.0
    n = int(round(duration * sr))
    t = np.arange(n, dtype=np.float64) / sr
    L = duration / np.log(f2 / f1)
    phase = 2.0 * np.pi * f1 * L * (np.exp(t / L) - 1.0)
    x = np.sin(phase) * (10.0 ** (LEVEL_DBFS / 20.0))
    fade_n = int(round(0.05 * sr))
    ramp = 0.5 - 0.5 * np.cos(np.linspace(0.0, np.pi, fade_n))
    x[:fade_n] *= ramp
    x[-fade_n:] *= ramp[::-1]
    return np.column_stack((x, x)).astype(np.float32)


def main():
    SIGNAL_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for sr in RATES:
        path = SIGNAL_DIR / f"sweep_log_m36-{sr}-tail.wav"
        sweep = create(sr)
        lead = np.zeros((int(0.5 * sr), 2), dtype=np.float32)
        tail = np.zeros((int(2.0 * sr), 2), dtype=np.float32)
        data = np.concatenate((lead, sweep, tail), axis=0)
        if path.exists():
            _, existing = wavfile.read(path)
            if not np.array_equal(existing, data):
                raise SystemExit(f"existing signal differs; refusing overwrite: {path}")
        else:
            wavfile.write(path, sr, data)
        rows.append({
            "path": str(path.relative_to(ROOT)).replace("\\", "/"),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "sample_rate_hz": sr,
            "samples": int(len(data)),
            "channels": 2,
            "format": "wav_float32",
            "type": "log_sweep",
            "level_dbfs": LEVEL_DBFS,
            "duration_total_s": len(data) / sr,
            "duration_sweep_s": 15.0,
            "f_start_hz": 1.0,
            "f_end_hz": 0.45 * sr,
            "fade_s": 0.05,
            "lead_s": 0.5,
            "tail_s": 2.0,
        })
    out = ROOT / "measurements/results/pultec_lf/lowlevel_grid_inputs.json"
    out.write_text(json.dumps({"schema": "altair-eq.lowlevel-grid-inputs/1", "files": rows},
                              ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"prepared {len(rows)} level-controlled input sweeps: {out}")


if __name__ == "__main__":
    main()
