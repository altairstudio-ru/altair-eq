#!/usr/bin/env python3
"""Retry one failed capped six-section LF fit from a looser-model warm start."""
import json
from pathlib import Path

import fit_pultec_lf_stable_sos as fitter

ROOT = Path(__file__).resolve().parents[2]
FIT = ROOT / "measurements/results/pultec_lf/stable_sos_six_section_fits.json"
CAP = ROOT / "measurements/results/pultec_lf/stable_sos_six_section_fits_r0999.json"
NODE_ID = "sr_reduced-30-b000-a100-48k-swp"


def main():
    fitter.SECTIONS = 6
    fitter.MAX_POLE_RADIUS = 0.999
    source = json.loads(FIT.read_text(encoding="utf-8"))
    capped = json.loads(CAP.read_text(encoding="utf-8"))
    reference = next(row for row in source["results"] if row["id"] == NODE_ID)
    row = next(row for row in capped["results"] if row["id"] == NODE_ID)
    sr = row["sample_rate_hz"]
    fit = fitter.fit_curve(ROOT / row["source"], sr, 20261111, reference["parameters"])
    fit.update({"id": NODE_ID, "sample_rate_hz": sr, "configuration": row["configuration"],
                "source": row["source"], "method_version": 2,
                "source_model": "retry from unconstrained six-section warm start under radius cap",
                "max_pole_radius_limit": fitter.MAX_POLE_RADIUS})
    upper = min(18000, sr / 2)
    fit["pass"] = (fit["max_pole_radius"] <= fitter.MAX_POLE_RADIUS and
                   fit["max_phase_error_deg"] <= 2.0 and
                   fit["band_max_magnitude_error_db"]["20-100"] <= .20 and
                   fit["band_max_magnitude_error_db"]["100-1000"] <= .15 and
                   fit["band_max_magnitude_error_db"][f"1000-{upper:g}"] <= .10)
    output = ROOT / "measurements/results/pultec_lf/single_node_cap_probe.json"
    output.write_text(json.dumps({"schema": "altair-eq.single-node-cap-probe/1", "result": fit},
                                 ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if fit["pass"]:
        capped["results"] = [fit if item["id"] == NODE_ID else item for item in capped["results"]]
        CAP.write_text(json.dumps(capped, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"pass": fit["pass"], "radius": fit["max_pole_radius"],
                      "magnitude": fit["band_max_magnitude_error_db"],
                      "phase_deg": fit["max_phase_error_deg"], "output": str(output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
