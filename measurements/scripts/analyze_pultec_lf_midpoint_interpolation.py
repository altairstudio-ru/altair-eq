#!/usr/bin/env python3
"""Compare SOS, complex-response, and log-response interpolation at measured half steps."""
import csv
import json
from pathlib import Path

import numpy as np
from scipy.interpolate import CubicSpline, PchipInterpolator

import fit_pultec_lf_stable_sos as fitter
from probe_pultec_lf_axis_interpolation import interpolate as interpolate_sos

ROOT = Path(__file__).resolve().parents[2]
FITS = ROOT / "measurements/results/pultec_lf/stable_sos_six_section_fits_r0999.json"
MEASUREMENTS = ROOT / "measurements/results/pultec_lf/interpolation_44k1_manifest.json"
OUT = ROOT / "measurements/results/pultec_lf/interpolation_44k1_analysis.json"
FLAT_CSV = ROOT / "measurements/results/pultec_lf/level_sweep_control_v2/flat-m36-44k1-sweep.csv"
FLAT_FIT = ROOT / "measurements/results/pultec_lf/flat_reference_fit.json"
SR = 44100


def read_target(path):
    with path.open(newline="", encoding="utf-8") as stream:
        data = list(csv.DictReader(stream))
    freq = np.array([float(x["freq_hz"]) for x in data])
    db = np.array([float(x["magnitude_db"]) for x in data])
    phase = np.deg2rad([float(x["phase_deg"]) for x in data])
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
    flat_fit = json.loads(FLAT_FIT.read_text(encoding="utf-8"))["result"]
    flat_freq, flat_response = read_target(FLAT_CSV)
    fit_map = {}
    for row in fits:
        c = row["configuration"]
        fit_map[(row["sample_rate_hz"], c["lf_cps_hz"], c["lf_boost_ui"], c["lf_atten_ui"])] = row
    measured = json.loads(MEASUREMENTS.read_text(encoding="utf-8"))
    results = []
    for row in measured["rows"].values():
        if row["status"] != "complete":
            raise SystemExit(f"incomplete midpoint measurement: {row['id']}")
        cps, axis, value = row["lf_cps_hz"], row["axis"], row[f"lf_{row['axis']}_ui"]
        if axis == "boost":
            low_control, high_control = int(value - .5), int(value + .5)
            low_key, high_key = (SR, cps, low_control, 0), (SR, cps, high_control, 0)
        else:
            low_control, high_control = int(value - .5), int(value + .5)
            low_key, high_key = (SR, cps, 0, low_control), (SR, cps, 0, high_control)
        right = fit_map[high_key]
        if low_control == 0:
            left = {"id": "flat_reference_44k1", "parameters": flat_fit["parameters"]}
        else:
            left = fit_map[low_key]
        t = .5
        freq, target = read_target(ROOT / row["analysis_csv"])
        if not np.array_equal(freq, flat_freq):
            raise SystemExit("flat reference frequency grid differs from interpolation sweeps")
        omega = 2 * np.pi * freq / SR
        h_left = fitter.response(left["parameters"], omega)
        h_right = fitter.response(right["parameters"], omega)
        sos_parameters = interpolate_sos(left["parameters"], right["parameters"], t)
        sos_response = fitter.response(sos_parameters, omega)
        complex_response = (1 - t) * h_left + t * h_right
        log_response = np.exp((1 - t) * np.log(np.abs(h_left)) + t * np.log(np.abs(h_right))
                              + 1j * ((1 - t) * np.unwrap(np.angle(h_left))
                                      + t * np.unwrap(np.angle(h_right))))
        controls = np.arange(0, 11, dtype=float)
        node_responses = [flat_response]
        for control in range(1, 11):
            key = (SR, cps, control, 0) if axis == "boost" else (SR, cps, 0, control)
            node_responses.append(fitter.response(fit_map[key]["parameters"], omega))
        node_responses = np.asarray(node_responses)
        log_magnitude = np.log(np.abs(node_responses))
        unwrapped_phase = np.unwrap(np.unwrap(np.angle(node_responses), axis=1), axis=0)
        pchip_response = np.exp(PchipInterpolator(controls, log_magnitude, axis=0)(value)
                                + 1j * PchipInterpolator(controls, unwrapped_phase, axis=0)(value))
        cubic_response = np.exp(CubicSpline(controls, log_magnitude, axis=0)(value)
                                + 1j * CubicSpline(controls, unwrapped_phase, axis=0)(value))
        results.append({"id": row["id"], "lf_cps_hz": cps, "axis": axis, "value": value,
                        "left_id": left["id"], "right_id": right["id"],
                        "sos_interpolation": metrics(sos_response, target, freq),
                        "complex_response_interpolation": metrics(complex_response, target, freq),
                        "log_response_interpolation": metrics(log_response, target, freq),
                        "pchip_log_response_interpolation": metrics(pchip_response, target, freq),
                        "cubic_log_response_interpolation": metrics(cubic_response, target, freq)})
    methods = ("sos_interpolation", "complex_response_interpolation", "log_response_interpolation",
               "pchip_log_response_interpolation", "cubic_log_response_interpolation")
    summary = {method: {"pass": sum(x[method]["pass"] for x in results), "total": len(results),
                        "max_phase_error_deg": max(x[method]["max_phase_error_deg"] for x in results),
                        "max_band_errors_db": {band: max(x[method]["band_max_magnitude_error_db"][band]
                                                          for x in results)
                                                for band in ("20-100", "100-1000", "1000-18000")}}
               for method in methods}
    OUT.write_text(json.dumps({"schema": "altair-eq.pultec-lf-midpoint-interpolation-analysis/1",
                               "measurements": str(MEASUREMENTS.relative_to(ROOT)).replace("\\", "/"),
                               "fit_source": str(FITS.relative_to(ROOT)).replace("\\", "/"),
                               "summary": summary, "results": results}, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"details: {OUT}")


if __name__ == "__main__":
    main()
