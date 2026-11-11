#!/usr/bin/env python3
"""Fit a capped six-section representation of the measured LF flat response."""
import json
from pathlib import Path

import fit_pultec_lf_stable_sos as fitter

ROOT = Path(__file__).resolve().parents[2]
CSV = ROOT / "measurements/results/pultec_lf/level_sweep_control_v2/flat-m36-44k1-sweep.csv"
OUT = ROOT / "measurements/results/pultec_lf/flat_reference_fit.json"
SR = 44100


def main():
    fitter.SECTIONS = 6
    fitter.MAX_POLE_RADIUS = .999
    fit = fitter.fit_curve(CSV, SR, 20261111)
    fit["pass"] = (fit["max_pole_radius"] <= .999 and fit["max_phase_error_deg"] <= 2
                   and fit["band_max_magnitude_error_db"]["20-100"] <= .20
                   and fit["band_max_magnitude_error_db"]["100-1000"] <= .15
                   and fit["band_max_magnitude_error_db"]["1000-18000"] <= .10)
    fit.update({"id": "flat_reference_44k1", "sample_rate_hz": SR,
                "source": str(CSV.relative_to(ROOT)).replace("\\", "/"),
                "method_version": 1})
    OUT.write_text(json.dumps({"schema": "altair-eq.pultec-lf-flat-reference-fit/1",
                               "sections": 6, "max_pole_radius": .999,
                               "result": fit}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"pass": fit["pass"], "pole_radius": fit["max_pole_radius"],
                      "band_max_magnitude_error_db": fit["band_max_magnitude_error_db"],
                      "max_phase_error_deg": fit["max_phase_error_deg"], "output": str(OUT)},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
