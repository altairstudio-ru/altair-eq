#!/usr/bin/env python3
"""Repeat selected reference renders to quantify sweep repeatability."""
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
OUT = ROOT / "measurements/results/pultec_lf/repeatability"
SR, LATENCY = 44100, 86
CPS_NORM = {20: 0.0, 30: 0.167, 60: 0.5, 100: 0.834}
CASES = ((20, 9, 5), (30, 6, 9), (60, 5, 7), (100, 9, 6))


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if not PLUGIN.exists() or not RENDERER.is_file():
        raise SystemExit("reference plugin or renderer is missing")
    data = json.loads(INPUTS.read_text(encoding="utf-8"))
    src_row = next(x for x in data["files"] if x["sample_rate_hz"] == SR)
    source = ROOT / src_row["path"]
    if digest(source) != src_row["sha256"]:
        raise SystemExit("source sweep hash mismatch")
    OUT.mkdir(parents=True, exist_ok=True)
    manifest_path = OUT / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {
        "schema": "altair-eq.pultec-lf-repeatability/1", "sample_rate_hz": SR,
        "source_sha256": src_row["sha256"], "latency_samples": LATENCY,
        "started_utc": datetime.now(timezone.utc).isoformat(), "results": []}
    existing = {(tuple(r["configuration"]), r["repeat"]): r for r in manifest["results"]}
    for cps, boost, atten in CASES:
        for rep in range(1, args.repeats + 1):
            if ((cps, boost, atten), rep) in existing:
                continue
            name = f"cps{cps}-b{boost:02d}-a{atten:02d}-r{rep:02d}"
            wav = OUT / f"{name}.wav"
            report, aj, ac = wav.with_suffix(".json"), OUT / f"{name}-analysis.json", OUT / f"{name}-analysis.csv"
            if any(p.exists() for p in (wav, report, aj, ac)):
                raise SystemExit(f"refusing to overwrite partial output: {name}")
            params = [f"0={CPS_NORM[cps]}", f"1={boost/10}", f"2={atten/10}",
                      "8=0.5", "9=0.5", "10=0.5", "11=0"]
            cmd = [str(RENDERER), str(PLUGIN), str(source), str(wav), *params,
                   f"--require-latency={LATENCY}"]
            run = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
            rr = json.loads(report.read_text(encoding="utf-8")) if report.exists() else {}
            if run.returncode or rr.get("latency_samples_reported") != LATENCY:
                raise SystemExit(f"render/latency failed {name}: {run.stderr[-600:]}")
            acmd = [sys.executable, str(ANALYZER), "transfer", str(source), str(wav), str(aj),
                    "--latency", str(LATENCY), "--fmin", "20", "--fmax", "18000", "--csv", str(ac)]
            analyzed = subprocess.run(acmd, cwd=ROOT, capture_output=True, text=True)
            if analyzed.returncode or not ac.is_file():
                raise SystemExit(f"analysis failed {name}: {analyzed.stderr[-600:]}")
            row = {"configuration": [cps, boost, atten], "repeat": rep,
                   "output": str(wav.relative_to(ROOT)).replace("\\", "/"),
                   "output_sha256": digest(wav), "analysis_csv": str(ac.relative_to(ROOT)).replace("\\", "/"),
                   "analysis_sha256": digest(ac), "latency_samples": LATENCY}
            manifest["results"].append(row)
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"complete {name}; latency={LATENCY}", flush=True)
    manifest["finished_utc"] = datetime.now(timezone.utc).isoformat()
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(manifest['results'])} repeat sweeps -> {manifest_path}")


if __name__ == "__main__":
    main()
