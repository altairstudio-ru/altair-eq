"""Этап 8: транспорт/seek/reset/bypass в REAPER + нагрузка.

Изолированный REAPER (WASAPI shared, частота устройства 96 кГц, мастер заглушен),
запись выхода трека в реальном времени, событийный таймлайн в Lua.
Анализ: сверка сегментов записи с офлайн-рендером того же сигнала через тот же
плагин (vst3render), точность seek, dry-совпадение при bypass, тишина при паузе.
Нагрузка: typeperf CPU процесса reaper во время воспроизведения.
Запускать вне sandbox (UADx).
"""
import argparse
import json
import shutil
import subprocess
import time
from pathlib import Path

import numpy as np
import psutil
import soundfile as sf
from scipy.signal import resample_poly

ROOT = Path(__file__).resolve().parents[2]
REAPER = Path(r"C:\Program Files\REAPER (x64)\reaper.exe")
SCRIPTS = ROOT / "measurements/scripts"
RESULTS = ROOT / "measurements/results/stage8"
RENDERS = ROOT / "measurements/renders/stage8"
SIGNALS = ROOT / "measurements/signals"
RENDERER = ROOT / "build-tools/vst3render_artefacts/Release/vst3render.exe"
ALTAIR_VST3 = Path(r"C:\Program Files\Common Files\VST3\AltaiR EQ LF.vst3")
UADX_VST3 = Path(r"C:\Program Files\Common Files\VST3\uaudio_pultec_eqp-1a.vst3")
CACHE_SRC = ROOT / "build/stage8/dev-wasapi-noin"
DISMISS = ROOT / "build/stage8/dismiss_dialogs.ps1"
RATE = 96000
GUARD = int(0.2 * RATE)  # 200 ms после события не сравниваем (settling LF-фильтров,
                         # crossfade bypass, транзиент pause/resume)


def music96():
    dest = SIGNALS / "stage8-music-96000.wav"
    if not dest.exists():
        src = SIGNALS / "stage8-music-44100.wav"
        if not src.exists():
            raise SystemExit("сначала check_stage8_render.py (создаёт 44.1k excerpt)")
        x, sr = sf.read(src, always_2d=True)
        y = resample_poly(x, 320, 147, axis=0)
        sf.write(dest, y, RATE, subtype="FLOAT")
    return dest


def offline_expected(plugin, signal):
    """Офлайн-рендер того же сигнала через тот же плагин (эталон для записи)."""
    out = RENDERS / f"daw-expected-{plugin}-{signal.stem}.wav"
    # устаревший кэш: сигнал новее рендера -> перерендерить (vst3render не
    # перезаписывает output, поэтому сначала удаляем wav и json)
    if (not out.exists()) or signal.stat().st_mtime > out.stat().st_mtime:
        for ext in (".wav", ".json"):
            p = out.with_suffix(ext)
            if p.exists():
                p.unlink()
        vst3 = ALTAIR_VST3 if plugin == "altair" else UADX_VST3
        if plugin == "altair":
            params = ["0=0.6666667", "1=0.7", "2=0.3", "3=1", "4=0.5", "5=0",
                      "--require-latency=0"]
        else:
            params = ["0=0.5", "1=0.7", "2=0.3", "8=0.5", "9=0.5", "10=0.5",
                      "11=0", "--require-latency=118"]
        subprocess.run([str(RENDERER), str(vst3), str(signal), str(out), *params],
                       check=True, cwd=ROOT, capture_output=True, text=True)
    y, sr = sf.read(out, always_2d=True)
    assert sr == RATE
    dry, _ = sf.read(signal, always_2d=True)
    assert abs(len(y) - len(dry)) < 2 * RATE, \
        f"эталон {len(y)} кадров != сигнал {len(dry)} (усечённый рендер?)"
    if plugin == "uadx":
        y = y[118:]  # компенсация задержки референса
    return y


def make_cfg(name, buffer):
    d = ROOT / "build/stage8" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "rec").mkdir(exist_ok=True)
    for f in ("reaper-vstplugins64.ini", "reaper-fxtags.ini", "reaper-reginfo2.ini"):
        if (CACHE_SRC / f).exists() and not (d / f).exists():
            shutil.copy(CACHE_SRC / f, d / f)
    # Канонический конфиг, записанный самим REAPER после выбора устройства
    # Analog Out 1/2 (Studio M PRO) через prefs: WASAPI shared 96 кГц работает.
    canon = (ROOT / "build/stage8/dev-drv-name/reaper.ini").read_text(encoding="ascii")
    ini = canon.replace("wasapi_bs=512", f"wasapi_bs={buffer}")
    (d / "reaper.ini").write_text(ini, encoding="ascii")
    return d


def reaper_running():
    r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq reaper.exe"],
                       capture_output=True, text=True)
    return "reaper.exe" in r.stdout


def wait_done(d, timeout=180):
    t0 = time.time()
    while time.time() - t0 < timeout:
        f = d / "result.txt"
        if f.exists():
            txt = f.read_text(encoding="utf-8", errors="replace")
            if "DONE" in txt or "ERROR" in txt:
                return txt
        time.sleep(1)
    return (d / "result.txt").read_text(encoding="utf-8", errors="replace") \
        if (d / "result.txt").exists() else "TIMEOUT no result"


def cleanup_dialogs(pid=None):
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
           "-File", str(DISMISS)]
    if pid:
        cmd += ["-TargetPid", str(pid)]
    subprocess.run(cmd, capture_output=True, text=True)


def run_session(name, job, buffer, cpu=False):
    d = make_cfg(name, buffer)
    (d / "job.json").write_text(json.dumps(job), encoding="utf-8")
    for f in (d / "rec").glob("*.wav"):
        try:
            f.unlink()
        except OSError as e:
            print(f"WARN: не удалось удалить {f.name}: {e}", flush=True)
    if (d / "result.txt").exists():
        (d / "result.txt").unlink()
    t_start = time.time()
    print(f"=== {name} (buffer {buffer}) ===", flush=True)
    proc = subprocess.Popen([str(REAPER), "-cfgfile", str(d / "reaper.ini"),
                             "-new", str(SCRIPTS / "stage8_transport.lua")],
                            cwd=ROOT)
    cpu_samples = None
    if cpu:
        time.sleep(4)  # дать воспроизведению начаться
        # PID-точный замер (psutil), а не typeperf \Process(reaper): иначе
        # счётчик мог бы захватить пользовательский REAPER без -cfgfile.
        # %% одного ядра: 100 = одно ядро полностью (как typeperf Process).
        try:
            p = psutil.Process(proc.pid)
            p.cpu_percent(None)  # базовая точка
            cpu_samples = [p.cpu_percent(interval=1) for _ in range(18)]
        except psutil.NoSuchProcess:
            cpu_samples = None
    txt = wait_done(d)
    print(txt, flush=True)
    # ждём выхода ИМЕННО нашего инстанса (proc.pid). Чужой REAPER (например,
    # пользовательская сессия без -cfgfile) не трогаем: cleanup только по его PID.
    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        cleanup_dialogs(pid=proc.pid)
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            print(f"WARN: reaper pid {proc.pid} не вышел после cleanup", flush=True)
    # REAPER копирует вставленный медиафайл в RECORD_PATH (dry-копия с именем
    # сигнала) — исключаем её; записи burst'ов сортируем по времени финализации
    signame = Path(job["signal"]).name
    recs = [p for p in (d / "rec").glob("*.wav")
            if p.stat().st_mtime >= t_start - 2 and p.name != signame]
    recs.sort(key=lambda p: p.stat().st_mtime)
    if not recs:
        print("WARN: свежая запись не найдена", flush=True)
    return {"name": name, "buffer": buffer, "log": txt,
            "recordings": [str(p) for p in recs],
            "recording": str(recs[-1]) if recs else None,
            "cpu_percent_one_core": cpu_samples}


def segcorr(rec, ref, start_rec, start_ref, length):
    """Нормированная корреляция сегмента записи с эталоном + поиск сдвига ±200 мс:
    грубо шаг 16, затем точно шаг 1 вокруг найденного (sample-exact alignment —
    на широкополосном сигнале ошибка в 8 сэмплов даёт ложный residual ~-10 dB)."""
    a = rec[start_rec:start_rec + length, 0]
    if len(a) < length:
        return (-2.0, 0)
    a2 = a[:length] - np.mean(a[:length])
    aa = np.sum(a2 * a2)

    def corr_at(shift):
        b = ref[start_ref + shift:start_ref + shift + length, 0]
        if len(b) < length:
            return -2.0
        b2 = b[:length] - np.mean(b[:length])
        denom = np.sqrt(aa * np.sum(b2 * b2))
        return float(np.sum(a2 * b2) / denom) if denom > 0 else -2.0

    win = int(0.2 * RATE)
    best = (-2.0, 0)
    for shift in range(-win, win + 1, 16):
        c = corr_at(shift)
        if c > best[0]:
            best = (c, shift)
    for shift in range(best[1] - 16, best[1] + 17):
        c = corr_at(shift)
        if c > best[0]:
            best = (c, shift)
    return best


def residual(rec, ref, start_rec, start_ref, length, guard=GUARD):
    a = rec[start_rec + guard:start_rec + length, 0]
    b = ref[start_ref + guard:start_ref + length, 0]
    n = min(len(a), len(b))
    if n == 0:
        return {"max_abs": None, "rms": None, "signal_rms": None,
                "rms_db_rel": None}
    d = a[:n] - b[:n]
    sig = np.sqrt(np.mean(b[:n] ** 2))
    return {"max_abs": float(np.max(np.abs(d))),
            "rms": float(np.sqrt(np.mean(d * d))),
            "signal_rms": float(sig),
            "rms_db_rel": float(20 * np.log10(np.sqrt(np.mean(d * d)) / sig))
            if sig > 0 else None}


def analyze_transport(run, plugin, signal):
    paths = run.get("recordings") or []
    if len(paths) < 5:
        return {"error": f"ожидалось 5 burst-файлов, получено {len(paths)}",
                "files": paths}
    bursts = []
    for p in paths[:5]:
        x, sr = sf.read(p, always_2d=True)
        assert sr == RATE, sr
        bursts.append(x)
    b1, b2, b3, b4, b5 = bursts
    ref = offline_expected(plugin, signal)
    dry, _ = sf.read(signal, always_2d=True)
    s = lambda t: int(t * RATE)
    d1, d2, d3 = len(b1) / RATE, len(b2) / RATE, len(b3) / RATE
    d4, d5 = len(b4) / RATE, len(b5) / RATE
    # каждый seek-burst стартует из известной material-позиции (file0 = matX);
    # длительность одиночного сегмента = фактическая длительность burst'а
    # (wall-тайминг событий даёт чуть более короткую запись)
    # guard — сколько секунд после старта сегмента пропускаем (settling);
    # resume после паузы требует ~1.2 с на установление LF-фильтров
    segments = [
        (b1, "play0",    0.0, d1,  0.0, "wet", 0.2),
        (b2, "seek6",    0.0, d2,  6.0, "wet", 0.2),
        (b3, "seek2",    0.0, d3,  2.0, "wet", 0.2),
        (b4, "reset0",   0.0, 1.8, 0.0, "wet", 0.2),
        (b4, "bypass",   2.0, 3.5, 2.0, "dry", 0.2),
        (b4, "wetagain", 3.5, d4,  3.5, "wet", 0.2),
        (b5, "reset0b",  0.0, 1.8, 0.0, "wet", 0.2),
        (b5, "resume",   2.0, d5,  2.0, "wet", 1.2),
    ]
    out = {"files": [{"path": p, "frames": len(x), "seconds": len(x) / RATE,
                      "peak": float(np.max(np.abs(x)))}
                     for p, x in zip(paths[:5], bursts)],
           "peak": float(max(np.max(np.abs(x)) for x in bursts)),
           "segments": []}
    for rec, name, t0, t1, mat, kind, gsec in segments:
        length = s(t1 - t0)
        source = dry if kind == "dry" else ref
        c, shift = segcorr(rec, source, s(t0), s(mat), length)
        r = residual(rec, source, s(t0), s(mat) + shift, length, guard=s(gsec))
        out["segments"].append({"name": name, "kind": kind, "corr": c,
                                "shift_samples": shift, "guard_s": gsec, **r})
    # пауза при записи не пишется в файл: burst5 (5 с wall) короче на ~1 с;
    # корректность resume подтверждается corr сегмента resume
    out["pause_excluded_seconds"] = float(5.0 - d5)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="имя сессии")
    ap.add_argument("--analyze-only", action="store_true")
    args = ap.parse_args()
    sig = music96()
    sessions = [
        ("altair-b512", {"plugin": "altair", "instances": 1, "signal": sig.as_posix(),
                         "mode": "transport"}, 512, False),
        ("altair-b128", {"plugin": "altair", "instances": 1, "signal": sig.as_posix(),
                         "mode": "transport"}, 128, False),
        ("altair-b64", {"plugin": "altair", "instances": 1, "signal": sig.as_posix(),
                        "mode": "transport"}, 64, False),
        ("altair-b32", {"plugin": "altair", "instances": 1, "signal": sig.as_posix(),
                        "mode": "transport"}, 32, False),
        ("uadx-b512", {"plugin": "uadx", "instances": 1, "signal": sig.as_posix(),
                       "mode": "transport"}, 512, False),
        ("altair-load1", {"plugin": "altair", "instances": 1, "signal": sig.as_posix(),
                          "mode": "load"}, 128, True),
        ("altair-load8", {"plugin": "altair", "instances": 8, "signal": sig.as_posix(),
                          "mode": "load"}, 128, True),
        ("uadx-load1", {"plugin": "uadx", "instances": 1, "signal": sig.as_posix(),
                        "mode": "load"}, 128, True),
    ]
    RESULTS.mkdir(parents=True, exist_ok=True)
    report_path = RESULTS / "daw-validation.json"
    report = {"schema": "altair-eq.stage8-daw/1", "device_rate_hz": RATE,
              "audio_mode": "WASAPI shared (частота устройства фиксирована 96 кГц)",
              "sessions": []}
    if report_path.exists() and args.analyze_only:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    for name, job, buffer, cpu in sessions:
        if args.only and name != args.only:
            continue
        if args.analyze_only:
            run = next(s for s in report["sessions"] if s["name"] == name)
        else:
            run = run_session(name, job, buffer, cpu)
            report["sessions"] = [s for s in report["sessions"]
                                  if s["name"] != name] + [run]
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=1)
                                   + "\n", encoding="utf-8")
        if job["mode"] == "transport" and run.get("recordings"):
            a = analyze_transport(run, job["plugin"], sig)
            run["analysis"] = a
            if "error" in a:
                print("  ANALYZE ERROR:", a["error"], flush=True)
            else:
                for seg in a["segments"]:
                    rr = seg["rms_db_rel"]
                    if rr is not None:
                        print(f"  {seg['name']:9s} corr={seg['corr']:.4f} "
                              f"shift={seg['shift_samples']:+6d} "
                              f"resid_rms={rr:.1f} dB rel max={seg['max_abs']:.3g}",
                              flush=True)
                    else:
                        print(f"  {seg['name']:9s} corr={seg['corr']:.4f} (пусто)",
                              flush=True)
                print(f"  pause_excluded={a['pause_excluded_seconds']:.3f}s "
                      f"peak={a['peak']:.3f}", flush=True)
        if run.get("cpu_percent_one_core"):
            v = np.array(run["cpu_percent_one_core"])
            run["cpu_summary"] = {"median": float(np.median(v)),
                                  "max": float(np.max(v)), "n": len(v)}
            print(f"  CPU % одного ядра: median={np.median(v):.1f} "
                  f"max={np.max(v):.1f}", flush=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=1)
                               + "\n", encoding="utf-8")
    print("report:", report_path, flush=True)


if __name__ == "__main__":
    main()