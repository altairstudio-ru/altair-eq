#!/usr/bin/env python3
"""Leave out integer nodes and interpolate between their sequentially fitted half-step neighbors."""
import csv
import json
from pathlib import Path

import numpy as np

import fit_pultec_lf_stable_sos as fitter
from probe_pultec_lf_axis_interpolation import interpolate as interpolate_sos

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "measurements/results/pultec_lf/stable_sos_six_section_fits_r0999.json"
CONTINUATION = ROOT / "measurements/results/pultec_lf/axis_continuation_fits.json"
OUT = ROOT / "measurements/results/pultec_lf/axis_continuation_cv.json"
SR = 44100


def read_target(path):
    with path.open(newline="", encoding="utf-8") as stream:
        data = list(csv.DictReader(stream))
    freq = np.array([float(x["freq_hz"]) for x in data])
    db = np.array([float(x["magnitude_db"]) for x in data])
    phase = np.deg2rad([float(x["phase_deg"]) for x in data])
    return freq, 10 ** (db / 20) * np.exp(1j * phase)


def score(parameters, target, freq):
    response = fitter.response(parameters, 2 * np.pi * freq / SR)
    error_db = 20 * np.log10(np.abs(response)) - 20 * np.log10(np.abs(target))
    error_phase = np.angle(response * np.conj(target)) * 180 / np.pi
    bands = {}
    for lo, hi in ((20, 100), (100, 1000), (1000, 18000)):
        mask = (freq >= lo) & (freq < hi if hi < 18000 else freq <= hi)
        bands[f"{lo}-{hi}"] = float(np.max(np.abs(error_db[mask])))
    phase = float(np.max(np.abs(error_phase[(freq >= 20) & (freq <= 18000)])))
    passed = bands["20-100"] <= .20 and bands["100-1000"] <= .15 and bands["1000-18000"] <= .10 and phase <= 2
    return {"band_max_magnitude_error_db": bands, "max_phase_error_deg": phase, "pass": passed}


def main():
    fitter.SECTIONS = 6
    base = json.loads(BASE.read_text(encoding="utf-8"))["results"]
    cont = json.loads(CONTINUATION.read_text(encoding="utf-8"))["results"]
    base_map = {}
    for row in base:
        c = row["configuration"]
        if row["sample_rate_hz"] == SR:
            base_map[(c["lf_cps_hz"], c["lf_boost_ui"], c["lf_atten_ui"])] = row
    cont_map = {x["id"]: x for x in cont}
    results = []
    for cps in (20, 30, 60, 100):
        for axis in ("boost", "atten"):
            for control in range(1, 10):
                def key(value):
                    return f"cps{cps}-{axis}-{value:04.1f}".replace(".", "p")
                left, right = cont_map[key(control - .5)], cont_map[key(control + .5)]
                if axis == "boost":
                    measured = base_map[(cps, control, 0)]
                else:
                    measured = base_map[(cps, 0, control)]
                parameters = interpolate_sos(left["parameters"], right["parameters"], .5)
                freq, target = read_target(ROOT / measured["source"])
                result = score(parameters, target, freq)
                result.update({"sample_rate_hz": SR, "lf_cps_hz": cps, "axis": axis,
                               "control": control, "left_id": left["id"], "right_id": right["id"],
                               "held_id": measured["id"]})
                results.append(result)
    summary = {"pass": sum(x["pass"] for x in results), "total": len(results),
               "max_phase_error_deg": max(x["max_phase_error_deg"] for x in results),
               "max_band_errors_db": {band: max(x["band_max_magnitude_error_db"][band] for x in results)
                                      for band in ("20-100", "100-1000", "1000-18000")}}
    OUT.write_text(json.dumps({"schema": "altair-eq.axis-continuation-cv/1",
                               "method": "interpolate root-matched six-section parameters between sequentially fitted half steps; compare to held-out integer sweep",
                               "summary": summary, "results": results}, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"details: {OUT}")


if __name__ == "__main__":
    main()
