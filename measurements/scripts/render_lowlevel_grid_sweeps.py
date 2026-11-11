#!/usr/bin/env python3
"""Render the complete static LF configuration grid with -36 dBFS sweeps.

Renders only static EQ configurations from the committed grid, replacing the
signal with the protocol-compliant low-level sweep at the same sample rate.
Outputs are isolated and resumable; never overwrites an existing WAV.
"""
import hashlib
import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GRID = ROOT / "measurements/grid/pultec_lf_grid.json"
INPUT_MANIFEST = ROOT / "measurements/results/pultec_lf/lowlevel_grid_inputs.json"
PLUGIN = Path(r"C:\Program Files\Common Files\VST3\uaudio_pultec_eqp-1a.vst3")
RENDERER = ROOT / "build-tools/vst3render_artefacts/Release/vst3render.exe"
OUT = ROOT / "measurements/renders/pultec_lf/lowlevel_grid"
MANIFEST = ROOT / "measurements/results/pultec_lf/lowlevel_grid_manifest.json"
CPS_NORM = {20: 0.0, 30: 0.167, 60: 0.5, 100: 0.834}
LATENCY = {44100: 86, 48000: 86, 96000: 118}
GROUPS = {"boost_only", "atten_only", "boost_atten_trick", "sr_reduced"}


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="render at most N pending rows")
    args = parser.parse_args()
    if not RENDERER.is_file() or not PLUGIN.exists():
        raise SystemExit("renderer or reference VST3 is missing")
    grid = json.loads(GRID.read_text(encoding="utf-8"))
    input_manifest = json.loads(INPUT_MANIFEST.read_text(encoding="utf-8"))
    input_by_sr = {x["sample_rate_hz"]: x for x in input_manifest["files"]}
    selected = [r for r in grid["rows"] if r["group"] in GROUPS and r["signal"] == "sweep_log"
                and r["plugin"].get("lf_cps_hz") is not None]
    if len(selected) != 152:
        raise SystemExit(f"expected 152 LF configurations (excluding two flat controls), found {len(selected)}")
    if set(input_by_sr) != set(LATENCY):
        raise SystemExit("low-level sweep inputs do not cover required sample rates")
    OUT.mkdir(parents=True, exist_ok=True)
    grid_sha = digest(GRID)
    input_shas = {str(sr): item["sha256"] for sr, item in input_by_sr.items()}
    if MANIFEST.exists():
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
        if data.get("grid_sha256") != grid_sha or data.get("input_sha256") != input_shas:
            raise SystemExit("grid or input hashes changed; refusing to resume mixed run")
    else:
        data = {
            "schema": "altair-eq.pultec-lf-lowlevel-grid/1",
            "grid_sha256": grid_sha,
            "input_sha256": input_shas,
            "started_utc": datetime.now(timezone.utc).isoformat(),
            "status": "running",
            "level_dbfs": -36,
            "rows": {},
        }
    attempted = 0
    for index, row in enumerate(selected, 1):
        rid = row["id"]
        old = data["rows"].get(rid)
        if old and old.get("status") == "complete":
            wav = ROOT / old["output"]
            report = ROOT / old["render_report"]
            if wav.is_file() and report.is_file() and digest(wav) == old["output_sha256"]:
                print(f"[{index}/{len(selected)}] already complete {rid}", flush=True)
                continue
            raise SystemExit(f"completed output missing or hash changed: {rid}")

        sr = row["sample_rate_hz"]
        source = ROOT / input_by_sr[sr]["path"]
        if digest(source) != input_by_sr[sr]["sha256"]:
            raise SystemExit(f"input hash changed: {source}")
        dest = OUT / f"{rid}-m36.wav"
        report = dest.with_suffix(".json")
        if old and old.get("status") == "running" and dest.is_file() and report.is_file():
            render_report = json.loads(report.read_text(encoding="utf-8"))
            if render_report.get("required_latency_samples") != LATENCY[sr] or \
                    render_report.get("latency_samples_reported") != LATENCY[sr]:
                raise SystemExit(f"interrupted output failed latency gate: {rid}")
            old["output_sha256"] = digest(dest)
            old["render_report"] = str(report.relative_to(ROOT)).replace("\\", "/")
            old["latency_reported"] = render_report.get("latency_samples_reported")
            old["status"] = "complete"
            MANIFEST.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"[{index}/{len(selected)}] recovered complete {rid}", flush=True)
            continue
        if dest.exists() or report.exists():
            raise SystemExit(f"refusing to overwrite incomplete output: {dest}")
        p = row["plugin"]
        params = [
            f"0={CPS_NORM[p['lf_cps_hz']]}",
            f"1={float(p['lf_boost_ui'] or 0) / 10.0}",
            f"2={float(p['lf_atten_ui'] or 0) / 10.0}",
            "8=0.5", "9=0.5", "10=0.5", "11=0",
        ]
        command = [str(RENDERER), str(PLUGIN), str(source), str(dest), *params,
                   f"--require-latency={LATENCY[sr]}"]
        entry = {
            "status": "running", "group": row["group"], "sample_rate_hz": sr,
            "configuration": p, "input": str(source.relative_to(ROOT)).replace("\\", "/"),
            "input_sha256": input_by_sr[sr]["sha256"],
            "output": str(dest.relative_to(ROOT)).replace("\\", "/"),
            "command": command,
        }
        data["rows"][rid] = entry
        MANIFEST.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        entry["stdout"] = result.stdout[-1200:]
        entry["stderr"] = result.stderr[-1200:]
        if result.returncode or not dest.is_file() or not report.is_file():
            entry["status"] = "failed"
            entry["returncode"] = result.returncode
            MANIFEST.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            raise SystemExit(f"render failed: {rid}; see {MANIFEST}")
        render_report = json.loads(report.read_text(encoding="utf-8"))
        entry["output_sha256"] = digest(dest)
        entry["render_report"] = str(report.relative_to(ROOT)).replace("\\", "/")
        entry["latency_reported"] = render_report.get("latency_samples_reported")
        entry["status"] = "complete"
        MANIFEST.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"[{index}/{len(selected)}] complete {rid} ({entry['stderr'].strip()})", flush=True)
        attempted += 1
        if args.limit and attempted >= args.limit:
            break
    data["status"] = "complete" if len(data["rows"]) == len(selected) and all(
        x["status"] == "complete" for x in data["rows"].values()) else "partial"
    data["finished_utc"] = datetime.now(timezone.utc).isoformat()
    MANIFEST.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(data['rows'])} low-level sweeps complete: {MANIFEST}")


if __name__ == "__main__":
    main()
