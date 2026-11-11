#!/usr/bin/env python3
"""Analyze the supplemental matched-level sweep renders (no audio rendering)."""
import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from scipy.io import wavfile

ROOT = Path(__file__).resolve().parents[2]
RENDER_MANIFEST = ROOT / "measurements/results/pultec_lf/level_sweep_control_v2_manifest.json"
ANALYZER = ROOT / "measurements/scripts/analyze.py"
OUT = ROOT / "measurements/results/pultec_lf/level_sweep_control_v2"
SUMMARY = ROOT / "measurements/results/pultec_lf/level_sweep_control_v2_analysis.json"


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def phase_delta(a, b):
    d = float(a) - float(b)
    return abs((d + 180.0) % 360.0 - 180.0)


def main():
    manifest = json.loads(RENDER_MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("status") != "complete" or len(manifest.get("rows", [])) != 7:
        raise SystemExit("expected seven completed sweep renders")
    OUT.mkdir(parents=True, exist_ok=True)
    reports = {}
    rows = []
    for row in manifest["rows"]:
        source = ROOT / row["input"]
        rendered = ROOT / row["output"]
        stem = row["id"]
        report, table = OUT / f"{stem}.json", OUT / f"{stem}.csv"
        cmd = [sys.executable, str(ANALYZER), "transfer", str(source), str(rendered), str(report),
               "--latency", str(manifest["latency_gate_samples"]), "--fmin", "20", "--fmax", "18000",
               "--csv", str(table)]
        result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        if result.returncode:
            raise SystemExit(f"analysis failed for {stem}: {result.stderr}")
        sr, audio = wavfile.read(rendered)
        rows.append({
            "id": stem,
            "config": row["config"],
            "level_dbfs": row["level_dbfs"],
            "repeat": row["repeat"],
            "input_sha256": row["input_sha256"],
            "output_sha256": sha(rendered),
            "sample_rate_hz": sr,
            "output_peak_linear": float(np.max(np.abs(audio.astype(np.float64)))),
            "output_peak_dbfs": float(20.0 * np.log10(max(np.max(np.abs(audio.astype(np.float64))), 1e-30))),
            "analysis_json": str(report.relative_to(ROOT)).replace("\\", "/"),
            "analysis_csv": str(table.relative_to(ROOT)).replace("\\", "/"),
            "analyzer_stdout": result.stdout.strip(),
        })
        reports[stem] = read_csv(table)

    comparisons = []
    for config in ("flat", "char60-b6-a4"):
        base_id = f"{config}-m36-44k1-sweep"
        base = reports[base_id]
        for level in (-24, -12):
            stem = f"{config}-m{abs(level)}-44k1-sweep"
            other = reports[stem]
            mag = [abs(float(a["magnitude_db"]) - float(b["magnitude_db"])) for a, b in zip(base, other)]
            phase = [phase_delta(a["phase_deg"], b["phase_deg"]) for a, b in zip(base, other)]
            comparisons.append({
                "config": config,
                "reference_level_dbfs": -36,
                "comparison_level_dbfs": level,
                "max_abs_magnitude_delta_db": max(mag),
                "median_abs_magnitude_delta_db": float(np.median(mag)),
                "max_abs_phase_delta_deg": max(phase),
                "frequency_points": len(mag),
                "control_points": [
                    {"freq_hz": float(f),
                     "magnitude_delta_db": float(next(float(x["magnitude_db"]) for x in other if float(x["freq_hz"]) == f) -
                                                   next(float(x["magnitude_db"]) for x in base if float(x["freq_hz"]) == f))}
                    for f in (20.0, 30.0, 50.0, 60.0, 100.0, 1000.0, 10000.0, 18000.0)
                ],
            })

    repeat = next(x for x in rows if x["repeat"])
    original = next(x for x in rows if x["config"] == repeat["config"] and
                    x["level_dbfs"] == repeat["level_dbfs"] and not x["repeat"])
    a = wavfile.read(ROOT / next(x["output"] for x in manifest["rows"] if x["id"] == repeat["id"]))[1]
    b = wavfile.read(ROOT / next(x["output"] for x in manifest["rows"] if x["id"] == original["id"]))[1]
    repeat_result = {
        "repeat_of": original["id"],
        "repeat": repeat["id"],
        "bit_identical_samples": bool(np.array_equal(a, b)),
        "sha256_equal": repeat["output_sha256"] == original["output_sha256"],
        "original_sha256": original["output_sha256"],
        "repeat_sha256": repeat["output_sha256"],
    }
    out = {
        "schema": "altair-eq.level-sweep-control-analysis/1",
        "method": "FFT transfer of log sweeps; each level compared with the -36 dBFS sweep of the same configuration; latency compensated by 86 samples",
        "rows": rows,
        "level_comparisons": comparisons,
        "repeat_check": repeat_result,
    }
    SUMMARY.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"renders": len(rows), "comparisons": comparisons, "repeat_check": repeat_result,
                      "summary": str(SUMMARY)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
