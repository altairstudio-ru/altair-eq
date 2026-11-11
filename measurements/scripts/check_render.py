"""Generate a stereo impulse and verify transparent/plugin offline renders."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from scipy.io import wavfile

p = argparse.ArgumentParser()
p.add_argument("mode", choices=["generate", "analyze"])
p.add_argument("input", type=Path)
p.add_argument("output", nargs="?", type=Path)
a = p.parse_args()
if a.mode == "generate":
    x = np.zeros((44100 * 4, 2), dtype=np.float32)
    x[44100, :] = 10 ** (-18 / 20)
    a.input.parent.mkdir(parents=True, exist_ok=True)
    wavfile.write(a.input, 44100, x)
else:
    sr, x = wavfile.read(a.input)
    rate, y = wavfile.read(a.output)
    assert rate == sr and x.shape == y.shape
    assert np.isfinite(y).all()
    delay = int(np.argmax(np.abs(y[:, 0])) - np.argmax(np.abs(x[:, 0])))
    # Peak alignment is diagnostic only: a coloured impulse can shift its peak.
    aligned = y[max(delay, 0):len(y) + min(delay, 0)]
    source = x[max(-delay, 0):len(x) - max(delay, 0)]
    result = {
        "input_sha256": hashlib.sha256(a.input.read_bytes()).hexdigest(),
        "output_sha256": hashlib.sha256(a.output.read_bytes()).hexdigest(),
        "sample_rate_hz": sr, "peak_delay_samples": delay,
        "peak_output": float(np.max(np.abs(y))),
        "aligned_null_peak": float(np.max(np.abs(aligned - source))),
        "stereo_difference_peak": float(np.max(np.abs(y[:, 0] - y[:, 1]))),
        "bit_identical_samples": bool(np.array_equal(x, y)),
    }
    a.output.with_suffix(".analysis.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
