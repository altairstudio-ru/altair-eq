"""Этап 8: слепые пары AltaiR EQ LF 0.1.3 vs UADx Pultec EQP-1A для прослушивания.

Сигналы: бас, кик, полный микс (отрывок 30-42 с). Две установки: 60 CPS
Boost 7/Atten 3 (типичная) и Boost 10/Atten 10 (максимальная). Рендер через
vst3render установленными VST3, задержка UADx compensated (86 сэмплов @44.1k),
уровень AltaiR выровнен по RMS к UADx, общий пик-нормализм 0.8. Порядок A/B
случайный, ключ в audit/key.json. Качество звука оценивает пользователь.
"""
import json
import secrets
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[2]
RENDERER = ROOT / "build-tools/vst3render_artefacts/Release/vst3render.exe"
ALTAIR = Path(r"C:\Program Files\Common Files\VST3\AltaiR EQ LF.vst3")
UADX = Path(r"C:\Program Files\Common Files\VST3\uaudio_pultec_eqp-1a.vst3")
RATE = 44100
LATENCY_UADX = 86
FOLDER = ROOT / "outputs/listening-stage8-20261117"
SETTINGS = [("typical", 7, 3), ("max", 10, 10)]


def signals():
    t = np.arange(RATE * 12) / RATE
    beat = t % 0.5
    notes = np.array([36.71, 36.71, 49, 55, 41.2, 41.2, 32.7, 49])[(t / .5).astype(int) % 8]
    phase = 2 * np.pi * notes * beat
    bass = ((np.sin(phase) + .35 * np.sin(2 * phase) + .12 * np.sin(3 * phase))
            * np.exp(-5 * beat) * np.minimum(beat / .008, 1) * np.minimum((.5 - beat) / .02, 1))
    f = 45 + 75 * np.exp(-beat / .03)
    kphase = 2 * np.pi * np.cumsum(f) / RATE
    kick = (np.sin(kphase) * np.exp(-beat / .12) * np.minimum(beat / .002, 1)
            + .4 * np.sin(2 * np.pi * 1800 * beat) * np.exp(-beat / .004))
    mix, sr = sf.read(next((ROOT / "eq_reaper_project/Media").glob("02 - *.wav")),
                      start=RATE * 30, frames=RATE * 12, always_2d=True)
    assert sr == RATE and mix.shape == (RATE * 12, 2)
    out = {}
    for label, x in (("bass", np.column_stack([bass, bass])),
                     ("kick", np.column_stack([kick, kick])), ("mix", mix)):
        x = x * (10 ** (-12 / 20) / np.max(np.abs(x)))
        n = int(0.01 * RATE)
        x[:n] *= np.linspace(0, 1, n)[:, None]
        x[-n:] *= np.linspace(1, 0, n)[:, None]
        out[label] = np.pad(x, ((RATE // 2, RATE // 2), (0, 0)))
    return out


def render(plugin, src, dst, setting, b, a):
    if plugin == "altair":
        params = ["0=0.6666667", f"1={b / 10}", f"2={a / 10}", "3=1", "4=0.5", "5=0",
                  "--require-latency=0"]
    else:
        params = ["0=0.5", f"1={b / 10}", f"2={a / 10}", "8=0.5", "9=0.5", "10=0.5", "11=0",
                  f"--require-latency={LATENCY_UADX}"]
    bundle = ALTAIR if plugin == "altair" else UADX
    subprocess.run([str(RENDERER), str(bundle), str(src), str(dst), *params], check=True)
    report = json.loads(dst.with_suffix(".json").read_text(encoding="utf-8"))
    assert report["latency_samples_reported"] == (0 if plugin == "altair" else LATENCY_UADX)
    y, sr = sf.read(dst, always_2d=True)
    assert sr == RATE
    if plugin == "uadx":
        y = y[LATENCY_UADX:]
    return y


def main():
    assert RENDERER.is_file() and ALTAIR.exists() and UADX.exists()
    FOLDER.mkdir(exist_ok=False)
    work = FOLDER / "audit"
    work.mkdir()
    manifest = {"schema": "altair-eq.stage8-listening/1", "rate": RATE,
                "altair_version": "0.1.3", "latency_uadx_samples": LATENCY_UADX,
                "level_match": "RMS AltaiR -> UADx, общий пик 0.8", "pairs": []}
    key = {}
    for label, x in signals().items():
        src = work / f"{label}-input.wav"
        sf.write(src, x, RATE, subtype="PCM_24")
        x, _ = sf.read(src, always_2d=True)
        for setting, b, a in SETTINGS:
            ya = render("altair", src, work / f"{label}-{setting}-altair.wav", setting, b, a)
            yu = render("uadx", src, work / f"{label}-{setting}-uadx.wav", setting, b, a)
            n = min(len(ya), len(yu))
            ya, yu = ya[:n], yu[:n]
            rms = lambda v: float(np.sqrt(np.mean(v * v)))
            ya = ya * (rms(yu) / rms(ya))
            gain = 0.8 / max(np.max(np.abs(ya)), np.max(np.abs(yu)))
            order = secrets.randbelow(2)
            name = f"{label}-{setting}"
            key[name] = "AB"[order]
            for letter, data in zip("AB", (yu, ya) if order == 0 else (ya, yu)):
                sf.write(FOLDER / f"{name}-{letter}.wav", gain * data, RATE, subtype="PCM_24")
            manifest["pairs"].append({
                "name": name, "cps": 60, "boost": b, "atten": a,
                "rms_altair_before_match": rms(ya), "rms_uadx": rms(yu),
                "peak_out": float(max(np.max(np.abs(ya)), np.max(np.abs(yu))) * gain),
                "frames": n})
            print(f"{name}: готово (ключ скрыт)", flush=True)
    (work / "key.json").write_text(json.dumps(key), encoding="utf-8")
    (work / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                                        encoding="utf-8")
    (FOLDER / "КАК СЛУШАТЬ.txt").write_text(
        "Слепые пары этапа 8: AltaiR EQ LF 0.1.3 и UADx Pultec EQP-1A.\n"
        "Файлы <сигнал>-<установка>-A/B.wav: bass/kick/mix, typical=60 CPS B7/A3,\n"
        "max=60 CPS B10/A10. Уровень выровнен по RMS, задержка UADx скомпенсирована.\n"
        "Какой файл какому плагину соответствует - в audit/key.json (не смотреть до конца).\n"
        "Слушать на одинаковой громкости, переключаться быстро; заметки по каждой паре.\n"
        "Исходники и сырые рендеры - в audit/.\n", encoding="utf-8")
    print("folder:", FOLDER, flush=True)


if __name__ == "__main__":
    main()