#!/usr/bin/env python3
"""Leave out quarter-step responses and predict them from measured neighboring control nodes."""
import csv
import json
from pathlib import Path

import numpy as np
from scipy.interpolate import CubicSpline, PchipInterpolator

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "measurements/results/pultec_lf/lowlevel_analysis_manifest.json"
HALVES = ROOT / "measurements/results/pultec_lf/interpolation_44k1_manifest.json"
QUARTERS = ROOT / "measurements/results/pultec_lf/interpolation_44k1_quarter_manifest.json"
FOCUSED = ROOT / "measurements/results/pultec_lf/interpolation_44k1_cps_focused_manifest.json"
EIGHTHS = ROOT / "measurements/results/pultec_lf/interpolation_44k1_eighth_manifest.json"
SIXTEENTHS = ROOT / "measurements/results/pultec_lf/interpolation_44k1_sixteenth_manifest.json"
OUT = ROOT / "measurements/results/pultec_lf/interpolation_44k1_quarter_analysis.json"
FLAT_CSV = ROOT / "measurements/results/pultec_lf/level_sweep_control_v2/flat-m36-44k1-sweep.csv"
SR = 44100


def read_curve(path):
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    freq = np.array([float(r["freq_hz"]) for r in rows])
    db = np.array([float(r["magnitude_db"]) for r in rows])
    phase = np.deg2rad([float(r["phase_deg"]) for r in rows])
    return freq, 10 ** (db / 20) * np.exp(1j * phase)


def evaluate(pred, ref, freq):
    err_db = 20 * np.log10(np.maximum(np.abs(pred), 1e-12)) - 20 * np.log10(np.abs(ref))
    err_phase = np.angle(pred * np.conj(ref)) * 180 / np.pi
    bands = {}
    for lo, hi in ((20, 100), (100, 1000), (1000, 18000)):
        mask = (freq >= lo) & (freq < hi if hi < 18000 else freq <= hi)
        bands[f"{lo}-{hi}"] = float(np.max(np.abs(err_db[mask])))
    phase = float(np.max(np.abs(err_phase[(freq >= 20) & (freq <= 18000)])))
    passed = bands["20-100"] <= .2 and bands["100-1000"] <= .15 and bands["1000-18000"] <= .1 and phase <= 2
    return {"band_max_magnitude_error_db": bands, "max_phase_error_deg": phase, "pass": passed}


def main():
    base = json.loads(BASE.read_text(encoding="utf-8"))["rows"]
    halves = json.loads(HALVES.read_text(encoding="utf-8"))["rows"]
    quarters = json.loads(QUARTERS.read_text(encoding="utf-8"))["rows"]
    focused = json.loads(FOCUSED.read_text(encoding="utf-8"))["rows"]
    eighths = json.loads(EIGHTHS.read_text(encoding="utf-8"))["rows"]
    sixteenths = json.loads(SIXTEENTHS.read_text(encoding="utf-8"))["rows"]
    family_rows = {}
    for row in base:
        if row["sample_rate_hz"] != SR:
            continue
        cfg = row["configuration"]
        if not ((cfg["lf_boost_ui"] > 0 and cfg["lf_atten_ui"] == 0)
                or (cfg["lf_atten_ui"] > 0 and cfg["lf_boost_ui"] == 0)):
            continue
        axis = "boost" if cfg["lf_boost_ui"] else "atten"
        value = float(cfg[f"lf_{axis}_ui"])
        family_rows.setdefault((cfg["lf_cps_hz"], axis), {})[value] = ROOT / row["analysis_csv"]
    for row in halves.values():
        if row["status"] == "complete":
            family_rows.setdefault((row["lf_cps_hz"], row["axis"]), {})[row[f"lf_{row['axis']}_ui"]] = ROOT / row["analysis_csv"]
    for row in quarters.values():
        if row["status"] == "complete":
            family_rows.setdefault((row["lf_cps_hz"], row["axis"]), {})[row[f"lf_{row['axis']}_ui"]] = ROOT / row["analysis_csv"]
    for row in focused.values():
        if row["status"] == "complete":
            family_rows.setdefault((row["lf_cps_hz"], row["axis"]), {})[row[f"lf_{row['axis']}_ui"]] = ROOT / row["analysis_csv"]
    for row in eighths.values():
        if row["status"] == "complete":
            family_rows.setdefault((row["lf_cps_hz"], row["axis"]), {})[row[f"lf_{row['axis']}_ui"]] = ROOT / row["analysis_csv"]
    for row in sixteenths.values():
        if row["status"] == "complete":
            family_rows.setdefault((row["lf_cps_hz"], row["axis"]), {})[row[f"lf_{row['axis']}_ui"]] = ROOT / row["analysis_csv"]
    for family in family_rows.values():
        family[0.0] = FLAT_CSV
    validation_rows = [("quarter", row) for row in quarters.values()]
    validation_rows.extend(("half", row) for row in halves.values())
    validation_rows.extend(("focused", row) for row in focused.values())
    validation_rows.extend(("eighth", row) for row in eighths.values())
    validation_rows.extend(("sixteenth", row) for row in sixteenths.values())
    results = []
    methods = ("linear_log", "pchip_log", "cubic_log")
    for grid_type, row in validation_rows:
        if row["status"] != "complete":
            raise SystemExit(f"incomplete quarter measurement: {row['id']}")
        cps, axis = row["lf_cps_hz"], row["axis"]
        value = row[f"lf_{axis}_ui"]
        family = family_rows[(cps, axis)]
        freq, target = read_curve(ROOT / row["analysis_csv"])
        xs = np.array(sorted(x for x in family if abs(x - value) > 1e-9), dtype=float)
        responses = np.array([read_curve(family[x])[1] for x in xs])
        log_mag = np.log(np.abs(responses))
        phase = np.unwrap(np.unwrap(np.angle(responses), axis=1), axis=0)
        lo, hi = max(x for x in xs if x < value), min(x for x in xs if x > value)
        mask = (xs == lo) | (xs == hi)
        fraction = (value - lo) / (hi - lo)
        linear_mag = (1 - fraction) * log_mag[mask][0] + fraction * log_mag[mask][1]
        linear_phase = (1 - fraction) * phase[mask][0] + fraction * phase[mask][1]
        predictions = {
            "linear_log": np.exp(linear_mag + 1j * linear_phase),
            "pchip_log": np.exp(PchipInterpolator(xs, log_mag, axis=0)(value)
                                + 1j * PchipInterpolator(xs, phase, axis=0)(value)),
            "cubic_log": np.exp(CubicSpline(xs, log_mag, axis=0)(value)
                                + 1j * CubicSpline(xs, phase, axis=0)(value)),
        }
        result = {"id": row["id"], "grid_type": grid_type,
                  "lf_cps_hz": cps, "axis": axis, "value": value,
                  "bracket": [float(lo), float(hi)]}
        for method in methods:
            result[method] = evaluate(predictions[method], target, freq)
        results.append(result)
    summary = {method: {"pass": sum(x[method]["pass"] for x in results), "total": len(results),
                        "max_phase_error_deg": max(x[method]["max_phase_error_deg"] for x in results),
                        "max_band_errors_db": {band: max(x[method]["band_max_magnitude_error_db"][band]
                                                          for x in results)
                                                for band in ("20-100", "100-1000", "1000-18000")}}
               for method in methods}
    OUT.write_text(json.dumps({"schema": "altair-eq.pultec-lf-quarter-interpolation/1",
                               "summary": summary, "results": results}, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"details: {OUT}")


if __name__ == "__main__":
    main()
