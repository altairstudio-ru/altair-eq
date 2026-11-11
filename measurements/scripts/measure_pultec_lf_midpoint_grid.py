#!/usr/bin/env python3
"""Render and analyze fractional LF Boost/Attenuation references at 44.1 kHz."""
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
OUTPUTS_ROOT = ROOT / "measurements/renders/pultec_lf"
RESULTS_ROOT = ROOT / "measurements/results/pultec_lf"
RATE = 44100
LATENCY = 86
CPS_NORMALIZED = {20: 0.0, 30: 0.167, 60: 0.5, 100: 0.834}
DEFAULT_VALUES = [x + 0.5 for x in range(10)]


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def build_rows(values):
    rows = []
    for cps in (20, 30, 60, 100):
        for axis in ("boost", "atten"):
            for value in values:
                boost, atten = (value, 0.0) if axis == "boost" else (0.0, value)
                if abs(value * 2 - round(value * 2)) < 1e-8:
                    precision = 1
                elif abs(value * 4 - round(value * 4)) < 1e-8:
                    precision = 2
                elif abs(value * 8 - round(value * 8)) < 1e-8:
                    precision = 3
                else:
                    precision = 4
                key = f"cps{cps}-{axis}-{value:04.{precision}f}".replace(".", "p")
                rows.append({"id": key, "lf_cps_hz": cps, "axis": axis,
                             "lf_boost_ui": boost, "lf_atten_ui": atten})
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="render at most N pending rows")
    parser.add_argument("--values", default=",".join(str(x) for x in DEFAULT_VALUES),
                        help="comma-separated LF control values")
    parser.add_argument("--tag", default="interpolation_44k1", help="unique output/manifest tag")
    args = parser.parse_args()
    values = [float(x) for x in args.values.split(",")]
    if not values or any(not 0 < value < 10 for value in values) or len(set(values)) != len(values):
        raise SystemExit("control values must be unique values strictly between 0 and 10")
    outputs = OUTPUTS_ROOT / args.tag
    manifest_path = RESULTS_ROOT / f"{args.tag}_manifest.json"
    if not PLUGIN.exists() or not RENDERER.is_file():
        raise SystemExit("reference plugin or renderer is missing")
    input_manifest = json.loads(INPUTS.read_text(encoding="utf-8"))
    input_row = next(x for x in input_manifest["files"] if x["sample_rate_hz"] == RATE)
    source = ROOT / input_row["path"]
    if digest(source) != input_row["sha256"]:
        raise SystemExit("low-level sweep input hash mismatch")
    outputs.mkdir(parents=True, exist_ok=True)
    if manifest_path.exists():
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        if data.get("input_sha256") != input_row["sha256"] or data.get("sample_rate_hz") != RATE:
            raise SystemExit("existing interpolation manifest has different input metadata")
    else:
        data = {"schema": "altair-eq.pultec-lf-interpolation-measurements/1",
                "sample_rate_hz": RATE, "latency_compensated_samples": LATENCY,
                "level_dbfs": -36, "input": str(source.relative_to(ROOT)).replace("\\", "/"),
                "input_sha256": input_row["sha256"], "started_utc": datetime.now(timezone.utc).isoformat(),
                "status": "running", "rows": {}}
    attempted = 0
    rows = build_rows(values)
    for index, row in enumerate(rows, 1):
        old = data["rows"].get(row["id"])
        if old and old.get("status") == "complete":
            wav = ROOT / old["output"]
            if wav.is_file() and digest(wav) == old["output_sha256"]:
                print(f"[{index}/{len(rows)}] already complete {row['id']}", flush=True)
                continue
            raise SystemExit(f"completed render missing or hash changed: {row['id']}")
        stem = row["id"]
        wav = outputs / f"{stem}.wav"
        render_json = wav.with_suffix(".json")
        analysis_json = outputs / f"{stem}-analysis.json"
        analysis_csv = outputs / f"{stem}-analysis.csv"
        if old and old.get("status") == "running" and wav.is_file() and render_json.is_file():
            report = json.loads(render_json.read_text(encoding="utf-8"))
            if report.get("latency_samples_reported") != LATENCY:
                raise SystemExit(f"interrupted render failed latency gate: {row['id']}")
            if not analysis_json.is_file() or not analysis_csv.is_file():
                analyze_command = [sys.executable, str(ANALYZER), "transfer", str(source), str(wav),
                                   str(analysis_json), "--latency", str(LATENCY), "--fmin", "20",
                                   "--fmax", "18000", "--csv", str(analysis_csv)]
                analyzed = subprocess.run(analyze_command, cwd=ROOT, capture_output=True, text=True)
                if analyzed.returncode or not analysis_json.is_file() or not analysis_csv.is_file():
                    raise SystemExit(f"recovered render analysis failed: {row['id']}")
            old.update({"status": "complete", "output_sha256": digest(wav),
                        "analysis_sha256": digest(analysis_csv),
                        "latency_reported_samples": LATENCY,
                        "recovered_utc": datetime.now(timezone.utc).isoformat()})
            manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"[{index}/{len(rows)}] recovered complete {row['id']}", flush=True)
            continue
        if wav.exists() or render_json.exists() or analysis_json.exists() or analysis_csv.exists():
            raise SystemExit(f"refusing to overwrite partial artifacts for {stem}")
        params = [f"0={CPS_NORMALIZED[row['lf_cps_hz']]}",
                  f"1={row['lf_boost_ui'] / 10.0}", f"2={row['lf_atten_ui'] / 10.0}",
                  "8=0.5", "9=0.5", "10=0.5", "11=0"]
        render_command = [str(RENDERER), str(PLUGIN), str(source), str(wav), *params,
                          f"--require-latency={LATENCY}"]
        entry = {**row, "sample_rate_hz": RATE, "level_dbfs": -36, "status": "running",
                 "input_sha256": input_row["sha256"],
                 "output": str(wav.relative_to(ROOT)).replace("\\", "/"),
                 "render_report": str(render_json.relative_to(ROOT)).replace("\\", "/"),
                 "analysis_json": str(analysis_json.relative_to(ROOT)).replace("\\", "/"),
                 "analysis_csv": str(analysis_csv.relative_to(ROOT)).replace("\\", "/"),
                 "render_command": render_command}
        data["rows"][row["id"]] = entry
        manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        rendered = subprocess.run(render_command, cwd=ROOT, capture_output=True, text=True)
        entry["render_stdout"] = rendered.stdout[-1000:]
        entry["render_stderr"] = rendered.stderr[-1000:]
        if rendered.returncode or not wav.is_file() or not render_json.is_file():
            entry["status"] = "failed"
            entry["returncode"] = rendered.returncode
            manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            raise SystemExit(f"render failed for {stem}; inspect {manifest_path}")
        report = json.loads(render_json.read_text(encoding="utf-8"))
        if report.get("latency_samples_reported") != LATENCY:
            entry["status"] = "failed"
            entry["reason"] = "unexpected plugin latency"
            manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            raise SystemExit(f"latency gate failed for {stem}")
        analyze_command = [sys.executable, str(ANALYZER), "transfer", str(source), str(wav),
                           str(analysis_json), "--latency", str(LATENCY), "--fmin", "20",
                           "--fmax", "18000", "--csv", str(analysis_csv)]
        analyzed = subprocess.run(analyze_command, cwd=ROOT, capture_output=True, text=True)
        if analyzed.returncode or not analysis_json.is_file() or not analysis_csv.is_file():
            entry["status"] = "failed"
            entry["analysis_stderr"] = analyzed.stderr[-1000:]
            manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            raise SystemExit(f"analysis failed for {stem}")
        entry.update({"status": "complete", "output_sha256": digest(wav),
                      "analysis_sha256": digest(analysis_csv),
                      "latency_reported_samples": report.get("latency_samples_reported")})
        manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"[{index}/{len(rows)}] complete {stem}; latency={LATENCY}", flush=True)
        attempted += 1
        if args.limit and attempted >= args.limit:
            break
    complete = len(data["rows"]) == len(rows) and all(x["status"] == "complete" for x in data["rows"].values())
    data["status"] = "complete" if complete else "partial"
    if complete:
        data["finished_utc"] = datetime.now(timezone.utc).isoformat()
    manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{sum(x['status'] == 'complete' for x in data['rows'].values())}/{len(rows)} complete -> {manifest_path}")


if __name__ == "__main__":
    main()
