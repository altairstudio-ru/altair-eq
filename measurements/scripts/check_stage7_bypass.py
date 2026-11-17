"""Проверка EQ In, host bypass и trim установленного VST3."""
from pathlib import Path
import subprocess
import tempfile
import numpy as np
from scipy.io import wavfile

ROOT = Path(__file__).resolve().parents[2]
HOST = ROOT / "build-tools/vst3render_artefacts/Release/vst3render.exe"
PLUGIN = Path("C:/Program Files/Common Files/VST3/AltaiR EQ LF.vst3")
source = ROOT / "measurements/signals/impulse-48000.wav"
rate, original = wavfile.read(source)
cases = [
    ("bypass", ["1=1", "2=0.5", "4=1", "5=1"], 1),
    ("eqout", ["1=1", "2=0.5", "3=0"], 1),
    ("trim", ["3=0", "4=0.75"], 10 ** (6 / 20)),
]
with tempfile.TemporaryDirectory(dir=ROOT / "build/stage7") as folder:
    for name, parameters, gain in cases:
        output = Path(folder) / (name + ".wav")
        subprocess.run([HOST, PLUGIN, source, output, *parameters, "--require-latency=0"], check=True)
        actual_rate, actual = wavfile.read(output)
        if actual.dtype == np.int32:
            actual = actual.astype(float) / (2 ** 31)
        error = float(np.max(np.abs(actual - original.astype(float) * gain)))
        if actual_rate != rate or error >= 1e-6:
            raise RuntimeError(f"{name}: ошибка {error}")
        print(f"{name}: PASS, max error {error:.9g}", flush=True)
