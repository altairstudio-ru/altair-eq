#!/usr/bin/env python3
"""Render controlled 44.1 kHz sweeps at three input levels.

Runs flat and CPS60/Boost6/Atten4 states at -36/-24/-12 dBFS, then repeats
the -24 dBFS character case in a fresh renderer process. Writes only under
measurements/renders/pultec_lf/level_sweep_control/ and records provenance.
Run outside the restricted sandbox because the licensed UADx plugin requires
its local authorization services.
"""
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = Path(r"C:\Program Files\Common Files\VST3\uaudio_pultec_eqp-1a.vst3")
RENDERER = ROOT / "build-tools/vst3render_artefacts/Release/vst3render.exe"
INPUTS = ROOT / "measurements/signals"
OUT = ROOT / "measurements/renders/pultec_lf/level_sweep_control_v2"
MANIFEST = ROOT / "measurements/results/pultec_lf/level_sweep_control_v2_manifest.json"
LATENCY = 86
LEVELS = (-36, -24, -12)
CONFIGS = {
    "flat": {"0": "0.5", "1": "0.0", "2": "0.0", "8": "0.5", "9": "0.5", "10": "0.5", "11": "0.0"},
    "char60-b6-a4": {"0": "0.5", "1": "0.6", "2": "0.4", "8": "0.5", "9": "0.5", "10": "0.5", "11": "0.0"},
}


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def input_path(level):
    if level == -12:
        return INPUTS / "sweep_log-44100.wav"
    return INPUTS / f"sweep_log_m{abs(level)}-44100-tail.wav"


def main():
    if not PLUGIN.exists() or not RENDERER.is_file():
        raise SystemExit("renderer or reference VST3 is missing")
    OUT.mkdir(parents=True, exist_ok=True)
    jobs = []
    for level in LEVELS:
        for config in CONFIGS:
            jobs.append((config, level, False))
    jobs.append(("char60-b6-a4", -24, True))
    for config, level, repeat in jobs:
        suffix = "-repeat" if repeat else ""
        wav = OUT / f"{config}-m{abs(level)}-44k1-sweep{suffix}.wav"
        report = wav.with_suffix(".json")
        if wav.exists() or report.exists():
            raise SystemExit(f"refusing to overwrite existing output: {wav}")

    record = {
        "schema": "altair-eq.level-sweep-control/1",
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "status": "running",
        "sample_rate_hz": 44100,
        "latency_gate_samples": LATENCY,
        "configs": CONFIGS,
        "rows": [],
    }
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for index, (config, level, repeat) in enumerate(jobs, 1):
        source = input_path(level)
        if not source.is_file():
            raise SystemExit(f"input signal missing: {source}")
        suffix = "-repeat" if repeat else ""
        wav = OUT / f"{config}-m{abs(level)}-44k1-sweep{suffix}.wav"
        params = [f"{key}={value}" for key, value in CONFIGS[config].items()]
        command = [str(RENDERER), str(PLUGIN), str(source), str(wav), *params,
                   f"--require-latency={LATENCY}"]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        row = {
            "id": wav.stem,
            "config": config,
            "level_dbfs": level,
            "repeat": repeat,
            "input": str(source.relative_to(ROOT)).replace("\\", "/"),
            "input_sha256": digest(source),
            "output": str(wav.relative_to(ROOT)).replace("\\", "/"),
            "command": command,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "status": "complete" if result.returncode == 0 and wav.is_file() else "failed",
        }
        if wav.is_file():
            row["output_sha256"] = digest(wav)
        report = wav.with_suffix(".json")
        if report.is_file():
            row["render_report"] = str(report.relative_to(ROOT)).replace("\\", "/")
        record["rows"].append(row)
        record["updated_utc"] = datetime.now(timezone.utc).isoformat()
        if row["status"] == "failed":
            record["status"] = "failed"
            MANIFEST.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            raise SystemExit(f"render failed for {row['id']}; see {MANIFEST}")
        MANIFEST.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"[{index}/{len(jobs)}] rendered {row['id']} ({row['stderr'].strip()})", flush=True)
    record["status"] = "complete"
    record["finished_utc"] = datetime.now(timezone.utc).isoformat()
    MANIFEST.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"complete: {len(jobs)} renders -> {MANIFEST}")


if __name__ == "__main__":
    main()
