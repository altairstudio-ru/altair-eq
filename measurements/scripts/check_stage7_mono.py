"""Системный VST3: моно-шина против автономного C++ DSP на трёх частотах."""
from pathlib import Path
import subprocess
import tempfile
import numpy as np
from scipy.io import wavfile

ROOT = Path(__file__).resolve().parents[2]
HOST = ROOT / "build-tools/vst3render_artefacts/Release/vst3render.exe"
DSP = ROOT / "build/stage6/Release/AltairEqFrozenImpulse.exe"
PLUGIN = Path("C:/Program Files/Common Files/VST3/AltaiR EQ LF.vst3")
with tempfile.TemporaryDirectory(dir=ROOT / "build/stage7") as folder:
    directory = Path(folder)
    for rate in (44100, 48000, 96000):
        source = directory / "source.wav"
        output = directory / f"mono-{rate}.wav"
        golden = directory / "golden.bin"
        samples = np.zeros((131072, 2), dtype=np.float32)
        samples[0] = (0.125, -0.0625)
        wavfile.write(source, rate, samples)
        subprocess.run([DSP, golden], input=f"{rate} 60 7 3\n", text=True, check=True)
        subprocess.run([HOST, PLUGIN, source, output, "0=0.6666667", "1=0.7",
                        "2=0.3", "--mono", "--require-latency=0"], check=True)
        actual_rate, actual = wavfile.read(output)
        if actual.dtype == np.int32:
            actual = actual.astype(float) / 2 ** 31
        expected = np.fromfile(golden, dtype="<f8") * 0.125
        if actual_rate != rate or actual.shape != expected.shape:
            raise RuntimeError("Expected mono output at source rate")
        error = float(np.max(np.abs(actual - expected)))
        if error >= 1e-7:
            raise RuntimeError(f"{rate}: {error}")
        print(f"{rate} Hz mono PASS, max error {error:.9g}", flush=True)
