#!/usr/bin/env python3
"""Render missing coarse two-control LF combinations for causal bilinear-bank probes."""
import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = Path(r"C:\Program Files\Common Files\VST3\uaudio_pultec_eqp-1a.vst3")
RENDERER = ROOT / "build-tools/vst3render_artefacts/Release/vst3render.exe"
ANALYZER = ROOT / "measurements/scripts/analyze.py"
INPUTS = ROOT / "measurements/results/pultec_lf/lowlevel_grid_inputs.json"
OUTPUT_DIR = ROOT / "measurements/renders/pultec_lf/joint_grid_44k1_coarse"
MANIFEST = ROOT / "measurements/results/pultec_lf/joint_grid_44k1_coarse_manifest.json"
CPS_NORMALIZED = {20: 0.0, 30: 0.167, 60: 0.5, 100: 0.834}
SR, LATENCY = 44100, 86


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def rows():
    result = []
    for cps in (20, 30, 60, 100):
        for boost in (2, 4, 6, 8, 10):
            for atten in (2, 4, 6, 8, 10):
                # Existing measured candidates: diagonal and two cross-check corners.
                if boost == atten or (boost, atten) in ((8, 2), (2, 8)):
                    continue
                rid = f"cps{cps}-b{boost:02d}-a{atten:02d}"
                result.append({"id": rid, "lf_cps_hz": cps,
                               "lf_boost_ui": float(boost), "lf_atten_ui": float(atten)})
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    if not PLUGIN.exists() or not RENDERER.is_file():
        raise SystemExit("reference plugin or renderer is missing")
    input_manifest = json.loads(INPUTS.read_text(encoding="utf-8"))
    input_row = next(x for x in input_manifest["files"] if x["sample_rate_hz"] == SR)
    source = ROOT / input_row["path"]
    if digest(source) != input_row["sha256"]:
        raise SystemExit("low-level sweep input hash mismatch")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if MANIFEST.exists():
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
        if data.get("input_sha256") != input_row["sha256"]:
            raise SystemExit("existing joint manifest input hash mismatch")
    else:
        data = {"schema": "altair-eq.pultec-lf-joint-grid-measurements/1",
                "sample_rate_hz": SR, "latency_compensated_samples": LATENCY,
                "level_dbfs": -36, "input": str(source.relative_to(ROOT)).replace("\\", "/"),
                "input_sha256": input_row["sha256"], "started_utc": datetime.now(timezone.utc).isoformat(),
                "status": "running", "rows": {}}
    todo = rows()
    attempted = 0
    for index, row in enumerate(todo, 1):
        old = data["rows"].get(row["id"])
        if old and old.get("status") == "complete":
            wav = ROOT / old["output"]
            if wav.is_file() and digest(wav) == old.get("output_sha256"):
                print(f"[{index}/{len(todo)}] already complete {row['id']}", flush=True)
                continue
            raise SystemExit(f"completed render missing or changed: {row['id']}")
        stem = row["id"]
        wav = OUTPUT_DIR / f"{stem}.wav"
        report_path = wav.with_suffix(".json")
        analysis_json = OUTPUT_DIR / f"{stem}-analysis.json"
        analysis_csv = OUTPUT_DIR / f"{stem}-analysis.csv"
        if any(p.exists() for p in (wav, report_path, analysis_json, analysis_csv)):
            raise SystemExit(f"refusing to overwrite partial output for {stem}")
        params = [f"0={CPS_NORMALIZED[row['lf_cps_hz']]}",
                  f"1={row['lf_boost_ui']/10.0}", f"2={row['lf_atten_ui']/10.0}",
                  "8=0.5", "9=0.5", "10=0.5", "11=0"]
        render = [str(RENDERER), str(PLUGIN), str(source), str(wav), *params,
                  f"--require-latency={LATENCY}"]
        entry = {**row, "sample_rate_hz": SR, "level_dbfs": -36, "status": "running",
                 "input_sha256": input_row["sha256"],
                 "output": str(wav.relative_to(ROOT)).replace("\\", "/"),
                 "render_report": str(report_path.relative_to(ROOT)).replace("\\", "/"),
                 "analysis_json": str(analysis_json.relative_to(ROOT)).replace("\\", "/"),
                 "analysis_csv": str(analysis_csv.relative_to(ROOT)).replace("\\", "/"),
                 "render_command": render}
        data["rows"][row["id"]] = entry
        MANIFEST.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        rendered = subprocess.run(render, cwd=ROOT, capture_output=True, text=True)
        report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
        if rendered.returncode or report.get("latency_samples_reported") != LATENCY:
            entry.update({"status": "failed", "returncode": rendered.returncode,
                          "stdout": rendered.stdout[-1000:], "stderr": rendered.stderr[-1000:],
                          "latency_samples_reported": report.get("latency_samples_reported")})
            MANIFEST.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            raise SystemExit(f"render/latency gate failed for {stem}")
        analyze = [sys.executable, str(ANALYZER), "transfer", str(source), str(wav), str(analysis_json),
                   "--latency", str(LATENCY), "--fmin", "20", "--fmax", "18000", "--csv", str(analysis_csv)]
        analyzed = subprocess.run(analyze, cwd=ROOT, capture_output=True, text=True)
        if analyzed.returncode or not analysis_json.is_file() or not analysis_csv.is_file():
            entry.update({"status": "failed", "analysis_stderr": analyzed.stderr[-1000:]})
            MANIFEST.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            raise SystemExit(f"analysis failed for {stem}")
        entry.update({"status": "complete", "output_sha256": digest(wav),
                      "analysis_sha256": digest(analysis_csv),
                      "latency_reported_samples": LATENCY})
        MANIFEST.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"[{index}/{len(todo)}] complete {stem}; latency={LATENCY}", flush=True)
        attempted += 1
        if args.limit and attempted >= args.limit:
            break
    complete = len(data["rows"]) == len(todo) and all(r["status"] == "complete" for r in data["rows"].values())
    data["status"] = "complete" if complete else "partial"
    if complete:
        data["finished_utc"] = datetime.now(timezone.utc).isoformat()
    MANIFEST.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{sum(r['status']=='complete' for r in data['rows'].values())}/{len(todo)} complete -> {MANIFEST}")


if __name__ == "__main__":
    main()
