"""Этап 8: плотная steady-state HF-сетка для потолка шестого исключения.

Авторитетная методика spot-sines (RMS синуса -36 dBFS, vst3render, окно 2 с),
расширенная на плотную сетку 1-18 кГц для 60/7/3 и 60/10/10 на 44.1/48/96 кГц.
Цель: фактический максимум |diff| в полосе 1-18 кГц -> потолок исключения
(округление вверх до 0.001 дБ, как пять принятых 16.11). Headless, без REAPER
и без аудиоустройства. Идемпотентно: существующие рендеры пропускаются.

--smoke: повторить 7 тонов spot-sines.json и сверить (регрессия методики).
"""
import argparse
import json
import math
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[2]
RENDERER = ROOT / "build-tools/vst3render_artefacts/Release/vst3render.exe"
ALTAIR_VST3 = Path(r"C:\Program Files\Common Files\VST3\AltaiR EQ LF.vst3")
UADX_VST3 = Path(r"C:\Program Files\Common Files\VST3\uaudio_pultec_eqp-1a.vst3")
SIGNALS = ROOT / "measurements/signals/hf-grid"
RENDERS = ROOT / "measurements/renders/stage8/hf-grid"
RESULTS = ROOT / "measurements/results/stage8"
LATENCY_UADX = {44100: 86, 48000: 86, 96000: 118}
AMP = 10 ** (-36 / 20)          # -36 dBFS
DUR = 3.0                        # с; окно анализа [1.0, 3.0] = 2 с steady-state
COMBOS = [(60, 7, 3), (60, 10, 10)]
SRATES = (44100, 48000, 96000)
TOL_HIGH = 0.10


def diff_db(rms_a, rms_u):
    return 20 * math.log10(rms_a / rms_u)


def tone_input(freq, sr):
    SIGNALS.mkdir(parents=True, exist_ok=True)
    p = SIGNALS / f"sine-{sr}-{freq}.wav"
    if not p.exists():
        t = np.arange(int(DUR * sr)) / sr
        mono = (AMP * np.sin(2 * np.pi * freq * t)).astype(np.float32)
        x = np.stack([mono, mono], axis=1)  # vst3render требует стерео-вход
        sf.write(p, x, sr, subtype="FLOAT")
    return p


def _valid_render(out, sr):
    """Кэш мог остаться усечённым после остановленного прогона — проверяем."""
    try:
        info = sf.info(out)
        return info.samplerate == sr and info.frames == int(DUR * sr)
    except Exception:
        return False


def render(plugin, cps, b, a, sr, freq):
    RENDERS.mkdir(parents=True, exist_ok=True)
    sig = tone_input(freq, sr)
    out = RENDERS / f"{plugin}-c{cps}-b{b}-a{a}-{sr}-{freq}.wav"
    if out.exists():
        if _valid_render(out, sr):
            return out
        out.unlink()  # битый/усечённый кэш -> перерендерить
        j = out.with_suffix(".json")
        if j.exists():
            j.unlink()
    if plugin == "altair":
        vst3, lat = ALTAIR_VST3, 0
        params = ["0=0.6666667", f"1={b/10}", f"2={a/10}", "3=1", "4=0.5", "5=0"]
    else:
        vst3, lat = UADX_VST3, LATENCY_UADX[sr]
        params = ["0=0.5", f"1={b/10}", f"2={a/10}", "8=0.5", "9=0.5", "10=0.5", "11=0"]
    subprocess.run([str(RENDERER), str(vst3), str(sig), str(out), *params,
                    f"--require-latency={lat}"],
                   check=True, cwd=ROOT, capture_output=True, text=True)
    return out


def measure(freq, sr, cps, b, a):
    ya, sa = sf.read(render("altair", cps, b, a, sr, freq), always_2d=True)
    yu, su = sf.read(render("uadx", cps, b, a, sr, freq), always_2d=True)
    assert sa == su == sr, (sa, su, sr)
    n = int(DUR * sr)
    assert len(ya) == len(yu) == n, (len(ya), len(yu), n)
    lo, hi = int(1.0 * sr), int(3.0 * sr)
    rms_a = float(np.sqrt(np.mean(ya[lo:hi, 0] ** 2)))
    rms_u = float(np.sqrt(np.mean(yu[lo:hi, 0] ** 2)))
    return {"freq_hz": freq, "srate": sr, "cps": cps, "boost": b, "atten": a,
            "rms_altair": rms_a, "rms_uadx": rms_u, "diff_db": diff_db(rms_a, rms_u)}


def grid_freqs():
    # Узкие HF-пики (напр. 17728 Гц @48k) требуют мелкого равномерного шага в
    # вершине полосы: грубый шаг 500 Гц пропускал пик между 17500 и 18000.
    coarse = list(range(1000, 8001, 1000))
    medium = list(range(8000, 15001, 500))
    fine = list(range(15000, 18001, 25))
    return sorted(set(coarse + medium + fine))


def refine_around(freq):
    lo = max(1000, freq - 40)
    hi = min(18000, freq + 40)
    return list(range(lo, hi + 1, 5))


def ceiling(max_abs):
    return math.ceil(max_abs * 1000) / 1000


def smoke():
    ref = json.loads((RESULTS / "spot-sines.json").read_text(encoding="utf-8"))
    print("smoke: повтор 7 тонов spot-sines.json", flush=True)
    ok = True
    for c in ref["checks"]:
        m = measure(c["freq_hz"], c["srate"], c["cps"], c["boost"], c["atten"])
        d = abs(m["diff_db"] - c["diff_db"])
        flag = "OK" if d <= 0.002 else "MISMATCH"
        if d > 0.002:
            ok = False
        print(f"  {c['freq_hz']:6d} @{c['srate']} c{c['cps']} b{c['boost']} "
              f"a{c['atten']}: new={m['diff_db']:+.4f} ref={c['diff_db']:+.4f} "
              f"delta={d:.4f} {flag}", flush=True)
    print("SMOKE", "PASS" if ok else "FAIL", flush=True)
    return ok


def run_grid():
    checks = []
    summary = []
    for sr in SRATES:
        for cps, b, a in COMBOS:
            seen = {}
            for f in grid_freqs():
                m = measure(f, sr, cps, b, a)
                seen[f] = m
                checks.append(m)
            peak_f = max(seen, key=lambda f: abs(seen[f]["diff_db"]))
            for f in refine_around(peak_f):
                if f in seen:
                    continue
                m = measure(f, sr, cps, b, a)
                seen[f] = m
                checks.append(m)
            peak_f = max(seen, key=lambda f: abs(seen[f]["diff_db"]))
            mx = abs(seen[peak_f]["diff_db"])
            exceeds = [f for f in seen if abs(seen[f]["diff_db"]) > TOL_HIGH]
            s = {"srate": sr, "cps": cps, "boost": b, "atten": a,
                 "max_abs_db": mx, "max_freq_hz": peak_f,
                 "ceiling_db": ceiling(mx), "exceeds_tol": mx > TOL_HIGH,
                 "n_tones": len(seen), "n_exceed_tones": len(exceeds),
                 "exceed_freqs_hz": sorted(exceeds)}
            summary.append(s)
            print(f"  c{cps} b{b} a{a} @{sr}: max={mx:.4f} dB @{peak_f} Hz "
                  f"ceiling={s['ceiling_db']:.3f} "
                  f"{'EXCEEDS' if s['exceeds_tol'] else 'within'} "
                  f"({len(exceeds)}/{len(seen)} тонов >0.10)", flush=True)
    report = {"schema": "altair-eq.stage8-hf-grid/1",
              "method": "steady-state RMS sine -36 dBFS, vst3render, окно 2 с [1,3]; "
                        "diff=20log10(RMS_altair/RMS_uadx); сетка 1-18 кГц + refine 20 Гц",
              "tol_high_db": TOL_HIGH, "summary": summary, "checks": checks}
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / "hf-grid.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n",
                   encoding="utf-8")
    print("report:", out, flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()
    if args.smoke:
        raise SystemExit(0 if smoke() else 1)
    run_grid()


if __name__ == "__main__":
    main()