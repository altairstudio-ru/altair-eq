#!/usr/bin/env python3
"""Fit measured LF single-control axes in order so adjacent SOS solutions can continue smoothly."""
import json
from pathlib import Path

import numpy as np

import fit_pultec_lf_stable_sos as fitter

ROOT = Path(__file__).resolve().parents[2]
FITS = ROOT / "measurements/results/pultec_lf/stable_sos_six_section_fits_r0999.json"
MIDPOINTS = ROOT / "measurements/results/pultec_lf/interpolation_44k1_manifest.json"
OUT = ROOT / "measurements/results/pultec_lf/axis_continuation_fits.json"
SR = 44100


def check_gate(fit, sr):
    upper = min(18000, sr / 2)
    return (fit["max_pole_radius"] <= fitter.MAX_POLE_RADIUS
            and fit["max_phase_error_deg"] <= 2
            and fit["band_max_magnitude_error_db"]["20-100"] <= .20
            and fit["band_max_magnitude_error_db"]["100-1000"] <= .15
            and fit["band_max_magnitude_error_db"][f"1000-{upper:g}"] <= .10)


def main():
    fitter.SECTIONS = 6
    fitter.MAX_POLE_RADIUS = .999
    source_fits = json.loads(FITS.read_text(encoding="utf-8"))["results"]
    fit_map = {}
    for row in source_fits:
        c = row["configuration"]
        fit_map[(c["lf_cps_hz"], c["lf_boost_ui"], c["lf_atten_ui"])] = row
    manifest = json.loads(MIDPOINTS.read_text(encoding="utf-8"))
    midpoint_map = manifest["rows"]
    if OUT.exists():
        saved = json.loads(OUT.read_text(encoding="utf-8"))
        if saved.get("source_fit") != str(FITS.relative_to(ROOT)).replace("\\", "/"):
            raise SystemExit("saved continuation set belongs to a different source fit")
        results = saved["results"]
    else:
        results = []
    result_map = {x["id"]: x for x in results}
    for cps in (20, 30, 60, 100):
        for axis in ("boost", "atten"):
            family = [x for x in midpoint_map.values() if x["lf_cps_hz"] == cps and x["axis"] == axis]
            family.sort(key=lambda x: x[f"lf_{axis}_ui"])
            warm = fit_map[(cps, 1, 0)]["parameters"] if axis == "boost" else fit_map[(cps, 0, 1)]["parameters"]
            for index, midpoint in enumerate(family, 1):
                control = midpoint[f"lf_{axis}_ui"]
                current = None
                if axis == "boost":
                    current = fit_map.get((cps, control, 0))
                else:
                    current = fit_map.get((cps, 0, control))
                if current is not None:
                    warm = current["parameters"]
                    continue
                rid = f"cps{cps}-{axis}-{control:04.1f}".replace(".", "p")
                if rid in result_map:
                    warm = result_map[rid]["parameters"]
                    continue
                if midpoint["status"] != "complete":
                    raise SystemExit(f"midpoint data is not complete: {rid}")
                fit = fitter.fit_curve(ROOT / midpoint["analysis_csv"], SR,
                                       cps * 100000 + index * 7919 + (0 if axis == "boost" else 1), warm)
                fit["pass"] = check_gate(fit, SR)
                fit.update({"id": rid, "sample_rate_hz": SR,
                            "configuration": {"lf_cps_hz": cps,
                                              "lf_boost_ui": control if axis == "boost" else 0,
                                              "lf_atten_ui": control if axis == "atten" else 0},
                            "source": midpoint["analysis_csv"], "axis": axis,
                            "control_value": control, "method_version": 1})
                result_map[rid] = fit
                warm = fit["parameters"]
                results = list(result_map.values())
                OUT.write_text(json.dumps({"schema": "altair-eq.axis-continuation-fit/1",
                                           "source_fit": str(FITS.relative_to(ROOT)).replace("\\", "/"),
                                           "measurements": str(MIDPOINTS.relative_to(ROOT)).replace("\\", "/"),
                                           "sample_rate_hz": SR, "max_pole_radius": .999,
                                           "results": results}, ensure_ascii=False, indent=2) + "\n",
                                encoding="utf-8")
                print(f"{rid}: {'PASS' if fit['pass'] else 'FAIL'} radius={fit['max_pole_radius']:.6f} "
                      f"phase={fit['max_phase_error_deg']:.3f}", flush=True)
    print(f"continuation fits: {sum(x['pass'] for x in results)}/{len(results)} pass -> {OUT}")


if __name__ == "__main__":
    main()
