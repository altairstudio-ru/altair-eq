#!/usr/bin/env python3
"""Fit stable SOS models to measured quarter-step LF axis nodes with local warm starts."""
import json
from pathlib import Path

import fit_pultec_lf_stable_sos as fitter

ROOT = Path(__file__).resolve().parents[2]
FIT_PATH = ROOT / "measurements/results/pultec_lf/stable_sos_six_section_fits_r0999.json"
HALF_PATH = ROOT / "measurements/results/pultec_lf/axis_continuation_fits.json"
FLAT_PATH = ROOT / "measurements/results/pultec_lf/flat_reference_fit.json"
MANIFESTS = [ROOT / f"measurements/results/pultec_lf/{name}" for name in (
    "interpolation_44k1_quarter_manifest.json", "interpolation_44k1_cps_focused_manifest.json",
    "interpolation_44k1_quarter_full_manifest.json")]
OUT = ROOT / "measurements/results/pultec_lf/quarter_node_fits.json"
SR = 44100


def passes(fit):
    return (fit["max_pole_radius"] <= .999
            and fit["max_phase_error_deg"] <= 2
            and fit["band_max_magnitude_error_db"]["20-100"] <= .2
            and fit["band_max_magnitude_error_db"]["100-1000"] <= .15
            and fit["band_max_magnitude_error_db"]["1000-18000"] <= .1)


def main():
    fitter.SECTIONS = 6
    fitter.MAX_POLE_RADIUS = .999
    integer_rows = json.loads(FIT_PATH.read_text(encoding="utf-8"))["results"]
    half_rows = json.loads(HALF_PATH.read_text(encoding="utf-8"))["results"]
    quarter_rows = []
    for manifest in MANIFESTS:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        if data.get("status") != "complete":
            raise SystemExit(f"incomplete measurement manifest: {manifest.name}")
        quarter_rows.extend(row for row in data["rows"].values() if row.get("status") == "complete")
    if len({r["id"] for r in quarter_rows}) != len(quarter_rows):
        raise SystemExit("duplicate quarter-node IDs across manifests")
    if OUT.exists():
        saved = json.loads(OUT.read_text(encoding="utf-8"))
        if saved.get("measurement_manifests") != [str(p.relative_to(ROOT)).replace("\\", "/") for p in MANIFESTS]:
            raise SystemExit("saved quarter fits belong to different manifests")
        fitted = {r["id"]: r for r in saved["results"]}
    else:
        fitted = {}

    anchors = {}
    for row in integer_rows:
        if row["sample_rate_hz"] != SR:
            continue
        c = row["configuration"]
        if c["lf_boost_ui"] and not c["lf_atten_ui"]:
            axis, value = "boost", float(c["lf_boost_ui"])
        elif c["lf_atten_ui"] and not c["lf_boost_ui"]:
            axis, value = "atten", float(c["lf_atten_ui"])
        else:
            continue
        anchors.setdefault((c["lf_cps_hz"], axis), {})[value] = row
    for row in half_rows:
        anchors.setdefault((row["configuration"]["lf_cps_hz"], row["axis"]), {})[float(row["control_value"])] = row
    flat_parameters = json.loads(FLAT_PATH.read_text(encoding="utf-8"))["result"]["parameters"]
    for cps in (20, 30, 60, 100):
        for axis in ("boost", "atten"):
            anchors.setdefault((cps, axis), {})[0.0] = {"parameters": flat_parameters}

    new_rows = []
    for row in quarter_rows:
        new_rows.append(row)
    for family in sorted({(r["lf_cps_hz"], r["axis"]) for r in new_rows}):
        cps, axis = family
        family_rows = sorted([r for r in new_rows if (r["lf_cps_hz"], r["axis"]) == family],
                             key=lambda r: float(r[f"lf_{axis}_ui"]))
        node_parameters = {value: row["parameters"] for value, row in anchors.get(family, {}).items()
                           if "parameters" in row}
        for index, row in enumerate(family_rows, 1):
            rid = row["id"]
            value = float(row[f"lf_{axis}_ui"])
            if rid in fitted:
                node_parameters[value] = fitted[rid]["parameters"]
                print(f"CPS {cps} {axis} [{index}/{len(family_rows)}] cached {value:g}", flush=True)
                continue
            lower = max(x for x in node_parameters if x < value)
            fit = fitter.fit_curve(ROOT / row["analysis_csv"], SR,
                                   int(cps * 100000 + round(value * 1000) * 31 + index * 7919),
                                   node_parameters[lower], max_starts=1, max_nfev=350)
            fit["pass"] = passes(fit)
            fit.update({"id": rid, "sample_rate_hz": SR,
                        "configuration": {"lf_cps_hz": cps,
                                          "lf_boost_ui": value if axis == "boost" else 0.0,
                                          "lf_atten_ui": value if axis == "atten" else 0.0},
                        "source": row["analysis_csv"], "axis": axis,
                        "control_value": value, "method_version": 1,
                        "warm_start_control": lower})
            fitted[rid] = fit
            node_parameters[value] = fit["parameters"]
            payload = {"schema": "altair-eq.pultec-lf-quarter-node-fits/1",
                       "source_integer_fits": str(FIT_PATH.relative_to(ROOT)).replace("\\", "/"),
                       "source_half_fits": str(HALF_PATH.relative_to(ROOT)).replace("\\", "/"),
                       "measurement_manifests": [str(p.relative_to(ROOT)).replace("\\", "/") for p in MANIFESTS],
                       "sample_rate_hz": SR, "max_pole_radius": .999,
                       "results": list(fitted.values())}
            OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"CPS {cps} {axis} [{index}/{len(family_rows)}] {value:g}: "
                  f"{'PASS' if fit['pass'] else 'FAIL'} r={fit['max_pole_radius']:.6f} "
                  f"phase={fit['max_phase_error_deg']:.3f}", flush=True)
    payload = {"schema": "altair-eq.pultec-lf-quarter-node-fits/1",
               "source_integer_fits": str(FIT_PATH.relative_to(ROOT)).replace("\\", "/"),
               "source_half_fits": str(HALF_PATH.relative_to(ROOT)).replace("\\", "/"),
               "measurement_manifests": [str(p.relative_to(ROOT)).replace("\\", "/") for p in MANIFESTS],
               "sample_rate_hz": SR, "max_pole_radius": .999,
               "results": list(fitted.values())}
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"quarter SOS fits: {sum(r['pass'] for r in fitted.values())}/{len(fitted)} pass -> {OUT}")


if __name__ == "__main__":
    main()
