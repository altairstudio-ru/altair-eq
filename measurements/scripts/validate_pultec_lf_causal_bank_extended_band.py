#!/usr/bin/env python3
"""Validate the frozen 44.1 kHz causal bank above 18 kHz using saved renders."""
import csv
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.io import wavfile

from probe_pultec_lf_causal_bank import basis

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "measurements/results/pultec_lf/causal_bank"
MANIFESTS = (
    ROOT / "measurements/results/pultec_lf/lowlevel_analysis_manifest.json",
    ROOT / "measurements/results/pultec_lf/joint_grid_44k1_coarse_manifest.json",
    ROOT / "measurements/results/pultec_lf/joint_grid_44k1_integer_manifest.json",
)
MODEL = OUT / "frozen_guard003_ridge0001_model.json"
SR = 44100
FMIN, FMAX = 18000.0, 0.45 * SR


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_rows():
    rows = {}
    for path in MANIFESTS:
        obj = json.loads(path.read_text(encoding="utf-8"))
        entries = obj["rows"]
        entries = entries.values() if isinstance(entries, dict) else entries
        for row in entries:
            if path.name == "lowlevel_analysis_manifest.json":
                if row.get("sample_rate_hz") != SR:
                    continue
                c = row["configuration"]
                cps, boost, atten = c["lf_cps_hz"], c["lf_boost_ui"], c["lf_atten_ui"]
                analysis = json.loads((ROOT / row["analysis_json"]).read_text(encoding="utf-8"))
                inputs = list(analysis["inputs"])
                row = {"sample_rate_hz": SR, "lf_cps_hz": cps, "lf_boost_ui": boost,
                       "lf_atten_ui": atten, "output": str(Path(inputs[1])),
                       "input": str(Path(inputs[0])), "output_sha256": row["output_sha256"],
                       "input_sha256": row["input_sha256"],
                       "latency_compensated_samples": row["latency_compensated_samples"]}
            else:
                if row.get("sample_rate_hz") != SR or row.get("status") != "complete":
                    continue
                cmd = row["render_command"]
                row["input"] = cmd[2]
            key = (int(row["lf_cps_hz"]), int(float(row["lf_boost_ui"])),
                   int(float(row["lf_atten_ui"])))
            rows.setdefault(key, row)
    flat_json = ROOT / "measurements/results/pultec_lf/level_sweep_control_v2/flat-m36-44k1-sweep.json"
    flat = json.loads(flat_json.read_text(encoding="utf-8"))
    inputs = list(flat["inputs"].items())
    flat_row = {
        "input": inputs[0][0], "input_sha256": inputs[0][1],
        "output": inputs[1][0], "output_sha256": inputs[1][1],
        "latency_compensated_samples": flat["latency_compensated_samples"],
    }
    for cps in (20, 30, 60, 100):
        rows[(cps, 0, 0)] = {**flat_row, "sample_rate_hz": SR, "lf_cps_hz": cps,
                             "lf_boost_ui": 0, "lf_atten_ui": 0}
    return rows


def measured_curve(row, grid):
    input_path, output_path = Path(row["input"]), Path(row["output"])
    input_sha, output_sha = row.get("input_sha256"), row.get("output_sha256")
    if input_sha and sha256(input_path) != input_sha:
        raise ValueError(f"input SHA-256 mismatch: {input_path}")
    if output_sha and sha256(output_path) != output_sha:
        raise ValueError(f"output SHA-256 mismatch: {output_path}")
    sr_x, x = wavfile.read(input_path)
    sr_y, y = wavfile.read(output_path)
    if sr_x != SR or sr_y != SR or x.shape != y.shape or x.ndim != 2 or x.shape[1] != 2:
        raise ValueError(f"unexpected WAV format or dimensions: {output_path}")
    x = x[:, 0].astype(np.float64)
    y = y[:, 0].astype(np.float64)
    X, Y = np.fft.rfft(x), np.fft.rfft(y)
    freqs = np.fft.rfftfreq(len(x), 1.0 / SR)
    power = np.abs(X) ** 2
    H = Y * np.conj(X) / (power + 1e-12 * np.max(power))
    latency = int(row.get("latency_compensated_samples", 86))
    H *= np.exp(1j * 2.0 * np.pi * freqs * latency / SR)
    valid = ((freqs >= FMIN) & (freqs <= FMAX) & (power > 1e-8 * np.max(power)))
    if np.count_nonzero(valid) < 16:
        raise ValueError(f"insufficient input energy above 18 kHz: {input_path}")
    src_f = freqs[valid]
    src_mag = 20 * np.log10(np.maximum(np.abs(H[valid]), 1e-30))
    src_phase = np.unwrap(np.angle(H[valid]))
    mag = np.interp(grid, src_f, src_mag)
    phase = np.interp(grid, src_f, src_phase)
    return 10 ** (mag / 20) * np.exp(1j * phase), mag


def main():
    model = json.loads(MODEL.read_text(encoding="utf-8"))
    poles = np.asarray(model["pole_real"]) + 1j * np.asarray(model["pole_imag"])
    grid = np.geomspace(FMIN, FMAX, 240)
    model_basis = basis(grid, poles)
    rows = load_rows()
    results = []
    for (cps, boost, atten), row in sorted(rows.items()):
        target, target_db = measured_curve(row, grid)
        weights = np.asarray(model["tables"][str(cps)])[boost, atten]
        pred = model_basis @ weights
        ratio = pred / target
        err_db = 20 * np.log10(np.maximum(np.abs(ratio), 1e-30))
        err_phase = np.angle(ratio, deg=True)
        i = int(np.argmax(np.abs(err_db)))
        results.append({
            "cps": cps, "boost": boost, "atten": atten,
            "max_abs_mag_error_db": float(abs(err_db[i])),
            "max_mag_error_hz": float(grid[i]),
            "max_abs_phase_error_deg": float(np.max(np.abs(err_phase))),
            "reference_peak_db": float(np.max(target_db)),
            "model_peak_db": float(np.max(20 * np.log10(np.maximum(np.abs(pred), 1e-30)))),
        })
    OUT.mkdir(parents=True, exist_ok=True)
    csv_path = OUT / "extended_band_validation.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(results[0]))
        w.writeheader()
        w.writerows(results)
    summary = {
        "model": str(MODEL.relative_to(ROOT)), "sample_rate_hz": SR,
        "band_hz": [FMIN, FMAX], "frequency_points_per_configuration": len(grid),
        "configuration_count": len(results),
        "max_abs_mag_error_db": max(r["max_abs_mag_error_db"] for r in results),
        "max_abs_phase_error_deg": max(r["max_abs_phase_error_deg"] for r in results),
        "max_reference_peak_db": max(r["reference_peak_db"] for r in results),
        "max_model_peak_db": max(r["model_peak_db"] for r in results),
        "csv": str(csv_path.relative_to(ROOT)),
        "note": "Saved -36 dBFS UADx renders only; errors above 18 kHz are diagnostic, outside SPEC gates.",
    }
    json_path = OUT / "extended_band_validation.json"
    json_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
