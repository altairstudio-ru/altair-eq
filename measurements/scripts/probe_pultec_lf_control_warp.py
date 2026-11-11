#!/usr/bin/env python3
"""Cross-validate a shared power-law control warp on measured 0.25/0.5/0.75 responses."""
import csv
import json
from pathlib import Path

import numpy as np
from scipy.optimize import minimize_scalar

import fit_pultec_lf_stable_sos as fitter

ROOT = Path(__file__).resolve().parents[2]
FITS = ROOT / "measurements/results/pultec_lf/stable_sos_six_section_fits_r0999.json"
QUARTERS = ROOT / "measurements/results/pultec_lf/interpolation_44k1_quarter_manifest.json"
HALVES = ROOT / "measurements/results/pultec_lf/interpolation_44k1_manifest.json"
OUT = ROOT / "measurements/results/pultec_lf/control_warp_probe.json"
FLAT = ROOT / "measurements/results/pultec_lf/level_sweep_control_v2/flat-m36-44k1-sweep.csv"
SR = 44100
TEST_VALUES = (0.25, 0.5, 0.75)


def read_curve(path):
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    freq = np.array([float(x["freq_hz"]) for x in rows])
    db = np.array([float(x["magnitude_db"]) for x in rows])
    phase = np.deg2rad([float(x["phase_deg"]) for x in rows])
    return freq, 10 ** (db / 20) * np.exp(1j * phase)


def metrics(prediction, target, freq):
    err_db = 20 * np.log10(np.maximum(np.abs(prediction), 1e-12)) - 20 * np.log10(np.abs(target))
    err_phase = np.angle(prediction * np.conj(target)) * 180 / np.pi
    bands = {}
    for lo, hi in ((20, 100), (100, 1000), (1000, 18000)):
        mask = (freq >= lo) & (freq < hi if hi < 18000 else freq <= hi)
        bands[f"{lo}-{hi}"] = float(np.max(np.abs(err_db[mask])))
    phase = float(np.max(np.abs(err_phase[(freq >= 20) & (freq <= 18000)])))
    passed = bands["20-100"] <= .2 and bands["100-1000"] <= .15 and bands["1000-18000"] <= .1 and phase <= 2
    return {"band_max_magnitude_error_db": bands, "max_phase_error_deg": phase, "pass": passed}


def main():
    fitter.SECTIONS = 6
    fits = json.loads(FITS.read_text(encoding="utf-8"))["results"]
    fit_map = {}
    for row in fits:
        c = row["configuration"]
        fit_map[(c["lf_cps_hz"], c["lf_boost_ui"], c["lf_atten_ui"])] = row
    paths = {}
    for fname in (HALVES, QUARTERS):
        rows = json.loads(fname.read_text(encoding="utf-8"))["rows"]
        for row in rows.values():
            axis = row["axis"]
            value = row[f"lf_{axis}_ui"]
            paths[(row["lf_cps_hz"], axis, value)] = ROOT / row["analysis_csv"]
    freq_flat, response_flat = read_curve(FLAT)
    families = []
    for cps in (20, 30, 60, 100):
        for axis in ("boost", "atten"):
            key = (cps, 1, 0) if axis == "boost" else (cps, 0, 1)
            response_one = fitter.response(fit_map[key]["parameters"], 2 * np.pi * np.linspace(20, 18000, 4096) / SR)
            freq0, response_half = read_curve(paths[(cps, axis, .5)])
            target_curves = {value: read_curve(paths[(cps, axis, value)])[1] for value in (.25, .5, .75)}
            families.append({"cps": cps, "axis": axis, "freq": freq0,
                             "response_flat": response_flat,
                             "response_one": fitter.response(fit_map[key]["parameters"], 2*np.pi*freq0/SR),
                             "target": target_curves})
    results = []
    for held_value in TEST_VALUES:
        train_values = [x for x in TEST_VALUES if x != held_value]

        def objective(power):
            total = 0.0
            count = 0
            for family in families:
                for value in train_values:
                    alpha = value ** power
                    log0 = np.log(np.abs(family["response_flat"])) + 1j*np.unwrap(np.angle(family["response_flat"]))
                    log1 = np.log(np.abs(family["response_one"])) + 1j*np.unwrap(np.angle(family["response_one"]))
                    pred = np.exp(log0 + alpha * (log1 - log0))
                    ref = family["target"][value]
                    mag = 20*np.log10(np.abs(pred/ ref))
                    phase = np.angle(pred*np.conj(ref))*180/np.pi
                    total += float(np.mean(mag**2 + (0.08*phase)**2))
                    count += len(mag)
            return total / count

        opt = minimize_scalar(objective, bounds=(.1, 3.0), method="bounded")
        held_results = []
        for family in families:
            alpha = held_value ** opt.x
            log0 = np.log(np.abs(family["response_flat"])) + 1j*np.unwrap(np.angle(family["response_flat"]))
            log1 = np.log(np.abs(family["response_one"])) + 1j*np.unwrap(np.angle(family["response_one"]))
            pred = np.exp(log0 + alpha * (log1 - log0))
            result = metrics(pred, family["target"][held_value], family["freq"])
            result.update({"lf_cps_hz": family["cps"], "axis": family["axis"], "control": held_value})
            held_results.append(result)
        results.append({"held_control": held_value, "power_exponent": float(opt.x),
                        "train_objective": float(opt.fun), "held_results": held_results})
    flat = [r for fold in results for r in fold["held_results"]]
    summary = {"pass": sum(x["pass"] for x in flat), "total": len(flat),
               "max_phase_error_deg": max(x["max_phase_error_deg"] for x in flat),
               "max_band_errors_db": {b: max(x["band_max_magnitude_error_db"][b] for x in flat)
                                      for b in ("20-100", "100-1000", "1000-18000")}}
    OUT.write_text(json.dumps({"schema": "altair-eq.control-warp-probe/1",
                               "method": "shared power-law u=x^p; p chosen from other two fractional controls and evaluated on held-out control across eight families",
                               "summary": summary, "folds": results}, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    print(json.dumps({"summary": summary,
                      "folds": [{"held": x["held_control"], "p": x["power_exponent"]} for x in results]},
                     ensure_ascii=False, indent=2))
    print(f"details: {OUT}")


if __name__ == "__main__":
    main()
