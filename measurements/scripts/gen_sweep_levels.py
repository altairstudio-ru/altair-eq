#!/usr/bin/env python3
"""Generate protocol-compliant supplemental 44.1 kHz log sweeps.

The prior v1 files lacked the required leading silence and tail. This generator
uses versioned filenames and includes the protocol's 0.5 s lead and 2 s tail.
"""
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.io import wavfile

ROOT = Path(__file__).resolve().parents[2]
SIGNAL_DIR = ROOT / "measurements/signals"
LEVELS = (-36, -24)
LEAD_S = 0.5
TAIL_S = 2.0
SR = 44100


def main():
    SIGNAL_DIR.mkdir(parents=True, exist_ok=True)
    results = []
    for level_dbfs in LEVELS:
        name = f"sweep_log_m{abs(level_dbfs)}-{SR}-tail.wav"
        path = SIGNAL_DIR / name
        if path.exists():
            raise SystemExit(f"refusing to overwrite existing signal: {path}")
        f1, f2, duration = 1.0, 0.45 * SR, 15.0
        n = int(round(duration * SR))
        t = np.arange(n, dtype=np.float64) / SR
        L = duration / np.log(f2 / f1)
        phase = 2.0 * np.pi * f1 * L * (np.exp(t / L) - 1.0)
        x = np.sin(phase) * (10.0 ** (level_dbfs / 20.0))
        fade_n = int(round(0.05 * SR))
        ramp = 0.5 - 0.5 * np.cos(np.linspace(0.0, np.pi, fade_n))
        x[:fade_n] *= ramp
        x[-fade_n:] *= ramp[::-1]
        signal = np.concatenate((np.zeros(int(LEAD_S * SR)), x, np.zeros(int(TAIL_S * SR))))
        stereo = np.column_stack((signal, signal)).astype(np.float32)
        path.parent.mkdir(parents=True, exist_ok=True)
        wavfile.write(path, SR, stereo)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        results.append({
            "path": str(path.relative_to(ROOT)).replace("\\", "/"),
            "sha256": digest,
            "sample_rate_hz": SR,
            "samples": int(len(stereo)),
            "channels": 2,
            "format": "wav_float32",
            "type": "log_sweep",
            "level_dbfs": level_dbfs,
            "duration_total_s": len(stereo) / SR,
            "duration_sweep_s": duration,
            "f_start_hz": f1,
            "f_end_hz": f2,
            "fade_s": 0.05,
            "lead_s": LEAD_S,
            "tail_s": TAIL_S,
        })
    manifest = {
        "schema": "altair-eq.level-sweep-inputs/1",
        "purpose": "Supplemental stage-4 level-dependence sweeps; no renders performed by this generator.",
        "files": results,
    }
    out = ROOT / "measurements/results/pultec_lf/level_sweep_inputs.json"
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"generated {len(results)} sweeps; manifest: {out}")


if __name__ == "__main__":
    main()
