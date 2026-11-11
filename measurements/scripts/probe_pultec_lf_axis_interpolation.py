#!/usr/bin/env python3
"""Leave-one-control-node-out check for LF SOS interpolation on existing measurements."""
import csv
import itertools
import json
from pathlib import Path

import numpy as np
from scipy.optimize import linear_sum_assignment

import fit_pultec_lf_stable_sos as fitter

ROOT = Path(__file__).resolve().parents[2]
FITS = ROOT / "measurements/results/pultec_lf/stable_sos_six_section_fits_r0999.json"
OUT = ROOT / "measurements/results/pultec_lf/axis_interpolation_probe.json"


def ordered_sections(parameters):
    gain = parameters[0]
    sections = np.asarray(parameters[1:], dtype=float).reshape(-1, 4)
    return gain, sections


def interpolate(left, right, fraction):
    lg, ls = ordered_sections(left)
    rg, rs = ordered_sections(right)
    def match_frequency(radius_index, angle_index):
        cost = np.empty((len(ls), len(rs)))
        for i, a in enumerate(ls):
            for j, b in enumerate(rs):
                cost[i, j] = abs(np.log(a[angle_index] / b[angle_index])) + abs(a[radius_index] - b[radius_index])
        rows, cols = linear_sum_assignment(cost)
        return rs[cols[np.argsort(rows)]]

    matched_poles = match_frequency(0, 1)
    matched_zeros = match_frequency(2, 3)
    params = np.empty_like(ls)
    params[:, 0] = ls[:, 0] * (1 - fraction) + matched_poles[:, 0] * fraction
    params[:, 1] = ls[:, 1] * (1 - fraction) + matched_poles[:, 1] * fraction
    params[:, 2] = ls[:, 2] * (1 - fraction) + matched_zeros[:, 2] * fraction
    params[:, 3] = ls[:, 3] * (1 - fraction) + matched_zeros[:, 3] * fraction
    return np.concatenate(([lg * (1 - fraction) + rg * fraction], params.ravel()))


def evaluate(parameters, row):
    with (ROOT / row["source"]).open(newline="", encoding="utf-8") as stream:
        data = list(csv.DictReader(stream))
    freq = np.array([float(x["freq_hz"]) for x in data])
    target_db = np.array([float(x["magnitude_db"]) for x in data])
    target_phase = np.deg2rad([float(x["phase_deg"]) for x in data])
    target = 10 ** (target_db / 20) * np.exp(1j * target_phase)
    omega = 2 * np.pi * freq / row["sample_rate_hz"]
    response = fitter.response(parameters, omega)
    mag_error = 20 * np.log10(np.abs(response)) - target_db
    phase_error = np.angle(response * np.conj(target)) * 180 / np.pi
    upper = min(18000, row["sample_rate_hz"] / 2)
    bands = {}
    for lo, hi in ((20, 100), (100, 1000), (1000, upper)):
        mask = (freq >= lo) & (freq <= hi if hi == upper else freq < hi)
        bands[f"{lo}-{hi:g}"] = float(np.max(np.abs(mag_error[mask])))
    passed = (bands["20-100"] <= .20 and bands["100-1000"] <= .15
              and bands[f"1000-{upper:g}"] <= .10 and np.max(np.abs(phase_error)) <= 2)
    return bands, float(np.max(np.abs(phase_error))), passed


def main():
    fitter.SECTIONS = 6
    fit_rows = json.loads(FITS.read_text(encoding="utf-8"))["results"]
    by_id = {x["id"]: x for x in fit_rows}
    groups = {}
    for row in fit_rows:
        config = row["configuration"]
        key = (row["sample_rate_hz"], config["lf_cps_hz"])
        groups.setdefault(key, []).append(row)
    results = []
    for (sr, cps), rows in sorted(groups.items()):
        for axis in ("lf_boost_ui", "lf_atten_ui"):
            varying = sorted({r["configuration"][axis] for r in rows
                              if (r["configuration"]["lf_atten_ui"] == 0 if axis == "lf_boost_ui"
                                  else r["configuration"]["lf_boost_ui"] == 0)})
            for control in varying[1:-1]:
                held = next((r for r in rows if r["configuration"][axis] == control
                             and (r["configuration"]["lf_atten_ui"] == 0 if axis == "lf_boost_ui"
                                  else r["configuration"]["lf_boost_ui"] == 0)), None)
                if held is None:
                    continue
                lower = max(v for v in varying if v < control)
                upper = min(v for v in varying if v > control)
                def find(value):
                    return next(r for r in rows if r["configuration"][axis] == value
                                and (r["configuration"]["lf_atten_ui"] == 0 if axis == "lf_boost_ui"
                                     else r["configuration"]["lf_boost_ui"] == 0))
                left, right = find(lower), find(upper)
                t = (control - lower) / (upper - lower)
                predicted = interpolate(by_id[left["id"]]["parameters"],
                                        by_id[right["id"]]["parameters"], t)
                bands, phase, passed = evaluate(predicted, held)
                results.append({"sample_rate_hz": sr, "lf_cps_hz": cps, "axis": axis,
                                "held_control": control, "bracket": [lower, upper],
                                "held_id": held["id"], "pass": passed,
                                "band_max_magnitude_error_db": bands,
                                "max_phase_error_deg": phase})
    OUT.write_text(json.dumps({"schema": "altair-eq.axis-interpolation-probe/1",
                               "method": "leave-one-out linear interpolation of matched SOS roots on single-control axes",
                               "fit_source": str(FITS.relative_to(ROOT)).replace("\\", "/"),
                               "results": results}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"axis interpolation: {sum(x['pass'] for x in results)}/{len(results)} pass -> {OUT}")
    for key, rows in itertools.groupby(sorted(results, key=lambda x: (x["sample_rate_hz"], x["lf_cps_hz"])),
                                       key=lambda x: (x["sample_rate_hz"], x["lf_cps_hz"])):
        rows = list(rows)
        print(f"  SR={key[0]} CPS={key[1]}: {sum(x['pass'] for x in rows)}/{len(rows)}")


if __name__ == "__main__":
    main()
