#!/usr/bin/env python3
"""Render the committed LF experiment grid through the installed UADx VST3.

Run this script outside a restricted sandbox: UADx requires its local services.
The manifest is resumable; successful WAV/JSON pairs are never overwritten.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GRID = ROOT / "measurements/grid/pultec_lf_grid.json"
PLUGIN = Path(r"C:\Program Files\Common Files\VST3\uaudio_pultec_eqp-1a.vst3")
RENDERER = ROOT / "build-tools/vst3render_artefacts/Release/vst3render.exe"
SIGNALS = ROOT / "measurements/signals"
OUT = ROOT / "measurements/renders/pultec_lf"
RESULTS = ROOT / "measurements/results/pultec_lf"
MANIFEST = RESULTS / "render_manifest.json"
LATENCY = {44100: 86, 48000: 86, 96000: 118}
CPS_NORM = {20: 0.0, 30: 0.167, 60: 0.5, 100: 0.834}
SIGNAL_NAME = {
    "impulse": "impulse", "sweep_log": "sweep_log", "sine_50": "sine_50",
    "sine_100": "sine_100", "sine_1000": "sine_1000",
    "twotone_50_1000": "twotone_50_1000",
}


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="render only first N selected rows")
    ap.add_argument("--groups", nargs="*", help="optional group filter")
    ap.add_argument("--force-corrected", action="store_true", help="write corrected rerenders with a new suffix")
    args = ap.parse_args()
    if not RENDERER.is_file() or not PLUGIN.exists():
        raise SystemExit("renderer or installed reference VST3 not found")
    grid = json.loads(GRID.read_text(encoding="utf-8"))
    rows = [r for r in grid["rows"] if not args.groups or r["group"] in args.groups]
    if args.limit:
        rows = rows[:args.limit]
    OUT.mkdir(parents=True, exist_ok=True)
    RESULTS.mkdir(parents=True, exist_ok=True)
    data = {"schema": "altair-eq.pultec-lf-render-manifest/1", "grid_sha256": sha(GRID),
            "started_utc": datetime.now(timezone.utc).isoformat(), "status": "running",
            "latency_samples": LATENCY, "rows": {}}
    if MANIFEST.exists():
        old = json.loads(MANIFEST.read_text(encoding="utf-8"))
        if old.get("grid_sha256") != data["grid_sha256"]:
            raise SystemExit("grid hash changed; refusing to mix runs")
        data["rows"].update(old.get("rows", {}))
    total = len(rows)
    for i, row in enumerate(rows, 1):
        rid = row["id"]
        if data["rows"].get(rid, {}).get("status") == "complete" and not args.force_corrected:
            continue
        sr = row["sample_rate_hz"]
        sig_key = SIGNAL_NAME[row["signal"]]
        level = row.get("level_dbfs")
        token = "" if level is None else "_m{}".format(abs(int(level)))
        source = SIGNALS / (sig_key + token + "-{}.wav".format({44100:"44100",48000:"48000",96000:"96000"}[sr]))
        if not source.is_file():
            raise SystemExit("missing input signal: " + str(source))
        dest = OUT / (rid + ("-corrected" if args.force_corrected else "") + ".wav")
        plugin = row["plugin"]
        if plugin["fx_present"]:
            cps = plugin["lf_cps_hz"] or 30
            boost = plugin["lf_boost_ui"] or 0
            atten = plugin["lf_atten_ui"] or 0
            trim = plugin["output_gain_ui"]
            params = ["0=" + str(CPS_NORM[cps]), "1=" + str(float(boost) / 10.0),
                      "2=" + str(float(atten) / 10.0), "8=" + ("0.5" if plugin["eq_in"] else "0"),
                      ("9db=" + str(float(trim)) if trim is not None else "9=0.5"), "10=0.5",
                      "11=" + ("0.5" if plugin["host_bypass"] else "0")]
            argv = [str(RENDERER), str(PLUGIN), str(source), str(dest), *params,
                    "--require-latency=" + str(LATENCY[sr])]
        else:
            argv = [str(RENDERER), "transparent", str(source), str(dest)]
        data["rows"][rid] = {"status": "running", "group": row["group"],
                             "signal": row["signal"], "sample_rate_hz": sr,
                             "input": str(source.relative_to(ROOT)),
                             "input_sha256": sha(source), "output": str(dest.relative_to(ROOT)),
                             "grid_row": row, "command": argv}
        MANIFEST.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("[{}/{}] {}".format(i, total, rid), flush=True)
        result = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True)
        entry = data["rows"][rid]
        entry["stdout"] = result.stdout[-2000:]
        entry["stderr"] = result.stderr[-2000:]
        if result.returncode != 0 or not dest.is_file() or not dest.with_suffix(".json").is_file():
            entry["status"] = "failed"
            entry["return_code"] = result.returncode
            MANIFEST.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            raise SystemExit("render failed; see manifest row " + rid)
        report = json.loads(dest.with_suffix(".json").read_text(encoding="utf-8"))
        entry["output_sha256"] = sha(dest)
        entry["render_report"] = str(dest.with_suffix(".json").relative_to(ROOT))
        entry["latency_reported"] = report.get("latency_samples_reported")
        entry["status"] = "complete"
        MANIFEST.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    selected_done = all(data["rows"].get(r["id"], {}).get("status") == "complete" for r in rows)
    data["status"] = "complete" if selected_done and len(data["rows"]) == grid["row_count"] else "partial"
    data["updated_utc"] = datetime.now(timezone.utc).isoformat()
    MANIFEST.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("{} rows complete; manifest {}".format(sum(v["status"] == "complete" for v in data["rows"].values()), MANIFEST))


if __name__ == "__main__":
    main()
