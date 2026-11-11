#!/usr/bin/env python3
"""Analyze the complete -36 dBFS sweep grid for DSP fitting and golden data."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "measurements/results/pultec_lf/lowlevel_grid_manifest.json"
ANALYZER = ROOT / "measurements/scripts/analyze.py"
OUT = ROOT / "measurements/results/pultec_lf/lowlevel_transfer"
SUMMARY = ROOT / "measurements/results/pultec_lf/lowlevel_analysis_manifest.json"
LATENCY = {44100: 86, 48000: 86, 96000: 118}


def main():
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if data.get("status") != "complete" or len(data.get("rows", {})) != 152:
        raise SystemExit("low-level grid manifest must contain 152 completed renders")
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for index, (rid, entry) in enumerate(data["rows"].items(), 1):
        if entry.get("status") != "complete":
            raise SystemExit(f"incomplete render: {rid}")
        source, rendered = ROOT / entry["input"], ROOT / entry["output"]
        stem = rid + "-m36"
        report, table = OUT / (stem + ".json"), OUT / (stem + ".csv")
        command = [sys.executable, str(ANALYZER), "transfer", str(source), str(rendered), str(report),
                   "--latency", str(LATENCY[entry["sample_rate_hz"]]), "--fmin", "20", "--fmax", "18000",
                   "--csv", str(table)]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        if result.returncode:
            raise SystemExit(f"analysis failed for {rid}: {result.stderr}")
        rows.append({
            "id": rid,
            "sample_rate_hz": entry["sample_rate_hz"],
            "configuration": entry["configuration"],
            "input_sha256": entry["input_sha256"],
            "output_sha256": entry["output_sha256"],
            "latency_compensated_samples": LATENCY[entry["sample_rate_hz"]],
            "analysis_json": str(report.relative_to(ROOT)).replace("\\", "/"),
            "analysis_csv": str(table.relative_to(ROOT)).replace("\\", "/"),
            "control_points": json.loads(report.read_text(encoding="utf-8"))["control_points"],
        })
        if index % 10 == 0:
            print(f"[{index}/152] analyzed {rid}", flush=True)
    summary = {
        "schema": "altair-eq.pultec-lf-lowlevel-analysis/1",
        "source_manifest": "measurements/results/pultec_lf/lowlevel_grid_manifest.json",
        "level_dbfs": -36,
        "frequency_range_hz": [20, 18000],
        "configurations": len(rows),
        "rows": rows,
    }
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"analysis complete: {len(rows)} configurations -> {SUMMARY}")


if __name__ == "__main__":
    main()
