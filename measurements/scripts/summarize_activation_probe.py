"""Diagnostic impulse comparison; not a calibrated linear transfer measurement."""
import hashlib
import json
from pathlib import Path
import numpy as np
from scipy.io import wavfile

root = Path(__file__).resolve().parents[2]
folder = root / "measurements/renders/calibration"
names = ["pultec-unsandboxed", "pultec-unsandboxed-flat", "pultec-unsandboxed-repeat"]
waves = []
hashes = {}
for name in names:
    path = folder / (name + ".wav")
    sr, wave = wavfile.read(path)
    assert sr == 44100 and wave.shape == (176400, 2) and np.isfinite(wave).all()
    waves.append(wave)
    hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
boost, flat, repeat = waves
freqs = np.fft.rfftfreq(len(boost), 1 / sr)
b, f = (np.fft.rfft(w[:, 0]) for w in (boost, flat))
result = {
    "status": "diagnostic; impulse response may include nonlinear effects",
    "sample_rate_hz": sr,
    "sha256": hashes,
    "repeat_bit_identical_samples": bool(np.array_equal(boost, repeat)),
    "repeat_difference_peak": float(np.max(np.abs(boost - repeat))),
    "boost_vs_flat_impulse_fft_db": {
        str(hz): float(20 * np.log10(abs(b[np.argmin(abs(freqs - hz))] / f[np.argmin(abs(freqs - hz))])))
        for hz in (20, 30, 60, 100, 1000)
    },
}
destination = root / "measurements/results/activation_probe.json"
destination.parent.mkdir(parents=True, exist_ok=True)
destination.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
print(json.dumps(result, indent=2))
