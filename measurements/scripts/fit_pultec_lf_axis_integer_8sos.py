#!/usr/bin/env python3
"""Refine measured integer Boost/Atten axis nodes with an eight-section stable fit."""
import json
from pathlib import Path

import numpy as np
import fit_pultec_lf_stable_sos as fitter

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "measurements/results/pultec_lf/lowlevel_analysis_manifest.json"
SIX = ROOT / "measurements/results/pultec_lf/stable_sos_six_section_fits_r0999.json"
OUT = ROOT / "measurements/results/pultec_lf/axis_integer_8sos_fits.json"
SR, MAX_RADIUS = 44100, .999


def pass_gate(fit):
    return (fit["max_pole_radius"] < 1.0
            and fit["max_phase_error_deg"] <= 2.0
            and fit["band_max_magnitude_error_db"]["20-100"] <= .20
            and fit["band_max_magnitude_error_db"]["100-1000"] <= .15
            and fit["band_max_magnitude_error_db"]["1000-18000"] <= .10)


def expand_six(parameters):
    low = [0.998, 2 * np.pi * 20 / SR, 0.998, 2 * np.pi * 20 / SR]
    high = [0.90, 2 * np.pi * 18000 / SR, 0.95, 2 * np.pi * 18000 / SR]
    # fitter.response consumes sections immediately after the scalar gain.
    # Append the two warm-start cancellations before, not after, the 6 SOS.
    return parameters[:1] + low + high + parameters[1:]


def main():
    fitter.SECTIONS = 8
    fitter.MAX_POLE_RADIUS = MAX_RADIUS
    rows = json.loads(BASE.read_text(encoding="utf-8"))["rows"]
    six_rows = json.loads(SIX.read_text(encoding="utf-8"))["results"]
    six_by_id = {row["id"]: row for row in six_rows}
    integer_axis = []
    for row in rows:
        if row["sample_rate_hz"] != SR:
            continue
        c = row["configuration"]
        b, a = float(c["lf_boost_ui"]), float(c["lf_atten_ui"])
        if b > 0 and a == 0 and b.is_integer():
            axis, value = "boost", int(b)
        elif a > 0 and b == 0 and a.is_integer():
            axis, value = "atten", int(a)
        else:
            continue
        if 1 <= value <= 10:
            integer_axis.append((c["lf_cps_hz"], axis, value, row))
    integer_axis.sort(key=lambda item: (item[0], item[1], item[2]))
    fitted = {}
    if OUT.exists():
        old = json.loads(OUT.read_text(encoding="utf-8"))
        fitted = {row["id"]: row for row in old["results"]}
    total = len(integer_axis)
    for index, (cps, axis, value, row) in enumerate(integer_axis, 1):
        rid = row["id"]
        if rid in fitted and fitted[rid]["pass"]:
            continue
        base = six_by_id[rid]
        warm = expand_six(base["parameters"])
        print(f"[{index}/{total}] CPS={cps} {axis}={value}", flush=True)
        fit = fitter.fit_curve(ROOT / row["analysis_csv"], SR,
                               int(cps * 100000 + (1000 if axis == "boost" else 2000)
                                   + value * 7919), warm,
                               max_starts=3, max_nfev=1200)
        fit["pass"] = pass_gate(fit)
        fit.update({"id": rid, "sample_rate_hz": SR, "configuration": row["configuration"],
                    "source": row["analysis_csv"], "axis": axis, "control_value": value,
                    "sections": 8, "source_six_fit": rid})
        fitted[rid] = fit
        payload = {"schema": "altair-eq.pultec-lf-axis-integer-8sos-fits/1",
                   "sample_rate_hz": SR, "max_pole_radius": MAX_RADIUS,
                   "fit_settings": {"max_starts": 3, "max_nfev": 1200},
                   "results": list(fitted.values())}
        OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"  {'PASS' if fit['pass'] else 'FIT-ONLY'} phase={fit['max_phase_error_deg']:.3f} deg; "
              f"max mag={fit['band_max_magnitude_error_db']}", flush=True)
    print(f"axis SOS fit: {sum(r['pass'] for r in fitted.values())}/{total} pass -> {OUT}")


if __name__ == "__main__":
    main()
