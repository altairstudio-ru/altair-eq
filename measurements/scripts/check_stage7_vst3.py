"""Сквозная стереопроверка Release VST3 по импульсу принятого C++ DSP."""
from pathlib import Path
import argparse
import subprocess
import tempfile

import numpy as np
from scipy.io import wavfile


ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "build/stage7/AltairEqLF_artefacts/Release/VST3/AltaiR EQ LF.vst3"
HOST = ROOT / "build-tools/vst3render_artefacts/Release/vst3render.exe"
DSP = ROOT / "build/stage6/Release/AltairEqFrozenImpulse.exe"


def check(directory, rate, plugin):
    source = directory / "input.wav"
    output = directory / f"output-{rate}.wav"
    golden = directory / "impulse.bin"
    scales = np.array([0.125, -0.0625])
    samples = np.zeros((131072, 2), dtype=np.float32)
    samples[0] = scales
    wavfile.write(source, rate, samples)
    subprocess.run([DSP, golden], input=f"{rate} 60 7 3\n", text=True, check=True)
    subprocess.run([HOST, plugin, source, output, "0=0.6666667", "1=0.7",
                    "2=0.3", "--require-latency=0"], check=True)
    actual_rate, actual = wavfile.read(output)
    expected = np.fromfile(golden, dtype="<f8")[:, None] * scales
    if actual_rate != rate or actual.shape != expected.shape:
        raise ValueError("Неверная частота или длина рендера")
    if np.issubdtype(actual.dtype, np.integer):
        actual = actual.astype(np.float64) / (1 << (8 * actual.itemsize - 1))
    error = np.max(np.abs(actual - expected))
    print(f"{rate} Hz: max |VST3 - DSP| = {error:.3g}", flush=True)
    if not error <= 1e-7:
        raise ValueError("Превышен допуск сквозной проверки")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--plugin", type=Path, default=PLUGIN,
                        help="VST3 bundle to verify; defaults to the stage7 build")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(dir=ROOT / "build/stage7") as folder:
        for sample_rate in (44100, 48000, 96000):
            check(Path(folder), sample_rate, args.plugin)
