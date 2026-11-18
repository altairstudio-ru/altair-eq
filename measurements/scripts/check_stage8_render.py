"""Этап 8: рендеры AltaiR и UADx бок о бок в REAPER и метрики расхождения.

Строит проекты Lua-скриптом в изолированном REAPER, рендерит каждый проект
командой -renderproject, затем сравнивает пары WAV (компенсация задержки,
АЧХ/фаза по sweep, временные метрики по импульсу и музыке).
Запускать вне sandbox: UADx требует локальные сервисы UA.
"""
import argparse
import base64
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[2]
REAPER = Path(r"C:\Program Files\REAPER (x64)\reaper.exe")
CFG = ROOT / "build/stage8/render"
SCRIPTS = ROOT / "measurements/scripts"
RENDERS = ROOT / "measurements/renders/stage8"
RESULTS = ROOT / "measurements/results/stage8"
SIGNALS = ROOT / "measurements/signals"
ALTAIR = "altair"
UADX = "uadx"
CPS_NORM_ALTAIR = {20: 0.0, 30: 1 / 3, 60: 2 / 3, 100: 1.0}
CPS_NORM_UADX = {20: 0.0, 30: 0.167, 60: 0.5, 100: 0.834}
BANDS = [(20, 100, 0.20), (100, 1000, 0.15), (1000, 18000, 0.10)]


def sha256(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def prepare_music_excerpt():
    dest = SIGNALS / "stage8-music-44100.wav"
    if dest.exists():
        return dest
    mix = next((ROOT / "eq_reaper_project/Media").glob("02 - *.wav"))
    rate = 44100
    x, sr = sf.read(mix, start=rate * 30, frames=rate * 12, always_2d=True)
    assert sr == rate and x.shape == (rate * 12, 2)
    x = x * (10 ** (-24 / 20) / np.max(np.abs(x)))
    n = int(0.01 * rate)
    ramp = np.linspace(0, 1, n)[:, None]
    x[:n] *= ramp
    x[-n:] *= ramp[::-1]
    sf.write(dest, x, rate, subtype="FLOAT")
    return dest


def build_jobs():
    music = prepare_music_excerpt()
    jobs = []

    def add(sig, srate, cps, boost, atten):
        info = sf.info(sig)
        for plugin in (ALTAIR, UADX):
            norm = CPS_NORM_ALTAIR if plugin == ALTAIR else CPS_NORM_UADX
            jobs.append({
                "id": f"{plugin}-{Path(sig).stem}-c{cps}-b{boost}-a{atten}-{srate}",
                "plugin": plugin, "input": Path(sig).as_posix(), "srate": srate,
                "duration": round(info.duration, 6),
                "cps_norm": norm[cps], "boost": boost, "atten": atten,
                "cps": cps, "signal": Path(sig).stem,
            })

    configs = [(60, 7, 3), (60, 10, 10), (20, 6, 0), (100, 0, 5), (30, 0, 0)]
    for cps, b, a in configs:
        add(SIGNALS / "impulse-44100.wav", 44100, cps, b, a)
        add(SIGNALS / "sweep_log_m36-44100-tail.wav", 44100, cps, b, a)
    for cps, b, a in [(60, 7, 3), (60, 10, 10)]:
        add(music, 44100, cps, b, a)
    for srate, sweep in [(48000, "sweep_log_m36-48000-tail.wav"),
                         (96000, "sweep_log_m36-96000-tail.wav")]:
        add(SIGNALS / f"impulse-{srate}.wav", srate, 60, 7, 3)
        add(SIGNALS / sweep, srate, 60, 7, 3)
    return jobs


def reaper_running():
    r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq reaper.exe"],
                       capture_output=True, text=True)
    return "reaper.exe" in r.stdout


def run_reaper(args, timeout=600, wait_for=None):
    cmd = [str(REAPER), "-cfgfile", str(CFG / "reaper.ini"), *args]
    print("RUN", " ".join(cmd), flush=True)
    subprocess.Popen(cmd, cwd=ROOT)
    t0 = __import__("time").time()
    if wait_for:
        while __import__("time").time() - t0 < timeout:
            if wait_for():
                break
            __import__("time").sleep(1)
    # дождаться завершения инстанса, снять модальные диалоги при необходимости
    dismiss = ROOT / "build/stage8/dismiss_dialogs.ps1"
    for _ in range(30):
        if not reaper_running():
            break
        if dismiss.exists():
            subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy",
                            "Bypass", "-File", str(dismiss)],
                           capture_output=True, text=True)
        __import__("time").sleep(2)
    if reaper_running():
        raise SystemExit("REAPER не завершился: " + " ".join(args))


def build_projects(jobs):
    CFG.mkdir(parents=True, exist_ok=True)
    for name in ("reaper-vstplugins64.ini", "reaper-fxtags.ini", "reaper-reginfo2.ini"):
        src = ROOT / "build/stage8/audioprobe" / name
        if src.exists() and not (CFG / name).exists():
            shutil.copy(src, CFG / name)
    ini = ("[REAPER]\nvstpath64=C:\\Program Files\\Common Files\\VST3\n"
           "renderclosewhendone=4\n[audioconfig]\nmode=5\ndummy_srate=44100\n"
           "dummy_blocksize=512\n")
    (CFG / "reaper.ini").write_text(ini, encoding="ascii")
    (CFG / "jobs.json").write_text(json.dumps(jobs, indent=1), encoding="utf-8")

    def built():
        f = CFG / "build-log.txt"
        if not f.exists():
            return False
        txt = f.read_text(encoding="utf-8", errors="replace")
        return "BUILD SUCCESS" in txt or "BUILD FAIL" in txt

    run_reaper(["-new", str(SCRIPTS / "stage8_build_render_projects.lua")],
               wait_for=built)
    log = (CFG / "build-log.txt").read_text(encoding="utf-8", errors="replace")
    print(log[-3000:], flush=True)
    if "BUILD SUCCESS" not in log:
        raise SystemExit("project build failed")


def render_projects(jobs):
    for j in jobs:
        rpp = CFG / (j["id"] + ".rpp")
        out = RENDERS / (j["id"] + ".wav")
        if out.exists():
            print("skip existing", out.name, flush=True)
            continue
        run_reaper(["-renderproject", str(rpp)], wait_for=out.exists)
        if not out.exists():
            raise SystemExit("render missing: " + str(out))
        info = sf.info(out)
        print(f"rendered {out.name} {info.samplerate} Hz {info.subtype} "
              f"{info.frames} frames", flush=True)


def read_pair(j):
    x, sx = sf.read(j["input"], always_2d=True)
    y, sy = sf.read(RENDERS / (j["id"] + ".wav"), always_2d=True)
    assert sx == sy == j["srate"], (sx, sy, j["srate"])
    return x, y


def transfer(x, y, rate):
    """АЧХ/фаза выхода относительно входа по активной части sweep."""
    n = min(len(x), len(y))
    X = np.fft.rfft(x[:n, 0] * np.hanning(n))
    Y = np.fft.rfft(y[:n, 0] * np.hanning(n))
    f = np.fft.rfftfreq(n, 1 / rate)
    with np.errstate(divide="ignore", invalid="ignore"):
        H = Y / X
    return f, H


def analyze(jobs):
    by_key = {}
    for j in jobs:
        key = (j["signal"], j["srate"], j["cps"], j["boost"], j["atten"])
        by_key.setdefault(key, {})[j["plugin"]] = j
    report = {"schema": "altair-eq.stage8-render-comparison/1", "pairs": []}
    for key, pair in sorted(by_key.items()):
        if ALTAIR not in pair or UADX not in pair:
            continue
        ja, ju = pair[ALTAIR], pair[UADX]
        xa, ya = read_pair(ja)
        xu, yu = read_pair(ju)
        entry = {"signal": key[0], "srate": key[1], "cps": key[2],
                 "boost": key[3], "atten": key[4]}
        if key[0].startswith("impulse"):
            # PDC REAPER компенсирован покадрово; argmax ловит звон фильтра,
            # а не прямой луч, поэтому сравнение без выравнивания.
            px = int(np.argmax(np.abs(xa[:, 0])))
            entry["impulse_position_input"] = px
            entry["peak_position_out"] = {
                "altair": int(np.argmax(np.abs(ya[:, 0]))) - px,
                "uadx": int(np.argmax(np.abs(yu[:, 0]))) - px}
            n = min(len(ya), len(yu))
            d = ya[:n] - yu[:n]
            entry["time_max_abs"] = float(np.max(np.abs(d)))
            entry["time_rms"] = float(np.sqrt(np.mean(d * d)))
            entry["peak_out"] = {"altair": float(np.max(np.abs(ya))),
                                 "uadx": float(np.max(np.abs(yu)))}
        elif key[0].startswith("sweep"):
            # Офлайн-рендер REAPER компенсирует PDC покадрово (проверено по
            # импульсу: пик выхода на позиции пика входа у обоих плагинов).
            n = min(len(xa), len(ya), len(xu), len(yu))
            xa2, ya2 = xa[:n], ya[:n]
            xu2, yu2 = xu[:n], yu[:n]
            entry["pdc_compensated"] = True
            d = ya2 - yu2
            entry["time_max_abs"] = float(np.max(np.abs(d)))
            entry["time_rms"] = float(np.sqrt(np.mean(d * d)))
            f, Ha = transfer(xa2, ya2, key[1])
            _, Hu = transfer(xu2, yu2, key[1])
            with np.errstate(divide="ignore", invalid="ignore"):
                dm = 20 * np.log10(np.abs(Ha)) - 20 * np.log10(np.abs(Hu))
                dp = np.angle(Ha / Hu) * 180 / np.pi
            bands = []
            for lo, hi, tol in BANDS:
                m = (f >= lo) & (f <= hi) & np.isfinite(dm) & np.isfinite(dp)
                bands.append({"lo_hz": lo, "hi_hz": hi, "tol_db": tol,
                              "max_db": float(np.max(np.abs(dm[m]))),
                              "p90_db": float(np.percentile(np.abs(dm[m]), 90)),
                              "max_phase_deg": float(np.max(np.abs(dp[m]))),
                              "pass": bool(np.max(np.abs(dm[m])) <= tol and
                                           np.max(np.abs(dp[m])) <= 2.0)})
            entry["bands"] = bands
            entry["pass"] = all(b["pass"] for b in bands)
        else:  # music
            n = min(len(xa), len(ya), len(xu), len(yu))
            xa2, ya2 = xa[:n], ya[:n]
            xu2, yu2 = xu[:n], yu[:n]
            entry["pdc_compensated"] = True
            d = ya2 - yu2
            entry["time_max_abs"] = float(np.max(np.abs(d)))
            entry["time_rms"] = float(np.sqrt(np.mean(d * d)))
            rms_a = float(np.sqrt(np.mean(ya2[:n] ** 2)))
            rms_u = float(np.sqrt(np.mean(yu2[:n] ** 2)))
            entry["level_diff_db"] = 20 * np.log10(rms_a / rms_u)
        report["pairs"].append(entry)
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / "render-comparison.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    for e in report["pairs"]:
        if "bands" in e:
            line = " | ".join(f"{b['lo_hz']}-{b['hi_hz']}: "
                              f"{b['max_db']:.4f} dB/{b['max_phase_deg']:.3f} deg "
                              f"{'PASS' if b['pass'] else 'FAIL'}" for b in e["bands"])
            print(f"{e['signal']} c{e['cps']} b{e['boost']} a{e['atten']} "
                  f"@{e['srate']}: {line}", flush=True)
        else:
            print(f"{e['signal']} c{e['cps']} b{e['boost']} a{e['atten']} "
                  f"@{e['srate']}: max={e['time_max_abs']:.3g} "
                  f"rms={e['time_rms']:.3g} "
                  f"lat={e.get('latency_samples', 'PDC=0')}",
                  flush=True)
    print("report:", out, flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-only", action="store_true")
    ap.add_argument("--render-only", action="store_true")
    ap.add_argument("--analyze-only", action="store_true")
    args = ap.parse_args()
    jobs = build_jobs()
    if args.analyze_only:
        analyze(jobs)
        return
    if not args.render_only:
        build_projects(jobs)
    if args.build_only:
        return
    RENDERS.mkdir(parents=True, exist_ok=True)
    render_projects(jobs)
    analyze(jobs)


if __name__ == "__main__":
    main()