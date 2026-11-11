#!/usr/bin/env python3
"""Build a six-section fit set with a hard pole-radius cap and resumable checkpoints."""
import json
from pathlib import Path

import numpy as np

import fit_pultec_lf_stable_sos as fitter


ROOT = Path(__file__).resolve().parents[2]
FOUR = ROOT / "measurements/results/pultec_lf/stable_sos_fits.json"
MANIFEST = ROOT / "measurements/results/pultec_lf/lowlevel_analysis_manifest.json"
OUT = ROOT / "measurements/results/pultec_lf/stable_sos_six_section_fits_r0999.json"


def pass_gate(fit, sr):
    upper = min(18000, sr / 2)
    return (fit["max_pole_radius"] < 1.0 and fit["max_phase_error_deg"] <= 2.0 and
            fit["band_max_magnitude_error_db"]["20-100"] <= 0.20 and
            fit["band_max_magnitude_error_db"]["100-1000"] <= 0.15 and
            fit["band_max_magnitude_error_db"][f"1000-{upper:g}"] <= 0.10)


def expand_four_section_fit(fit, sr):
    params = fit["parameters"]
    low = [0.998, 2 * np.pi * 20 / sr, 0.998, 2 * np.pi * 20 / sr]
    high = [0.90, 2 * np.pi * 18000 / sr, 0.90, 2 * np.pi * 18000 / sr]
    expanded = dict(fit)
    expanded["parameters"] = params + low + high
    expanded["max_pole_radius"] = max(fit["max_pole_radius"], 0.998)
    expanded["pass"] = True
    expanded["source_model"] = "four-section fit padded with exact pole-zero cancellations"
    return expanded


def main():
    fitter.SECTIONS = 6
    fitter.MAX_POLE_RADIUS = 0.999
    four_data = json.loads(FOUR.read_text(encoding="utf-8"))["results"]
    four_by_id = {row["id"]: row for row in four_data}
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if OUT.exists():
        saved = json.loads(OUT.read_text(encoding="utf-8"))
        results = [row for row in saved["results"]
                   if row.get("method_version") == 2
                   and row.get("max_pole_radius", 1.0) <= fitter.MAX_POLE_RADIUS]
    else:
        results = []
    by_id = {row["id"]: row for row in results}
    for index, row in enumerate(manifest["rows"], 1):
        rid = row["id"]
        base = four_by_id[rid]
        sr = int(row["sample_rate_hz"])
        if rid in by_id:
            print(f"[{index}/{len(manifest['rows'])}] already fitted {rid}", flush=True)
            continue
        if base["pass"] and base["max_pole_radius"] <= fitter.MAX_POLE_RADIUS:
            fit = expand_four_section_fit(base, sr)
            print(f"[{index}/{len(manifest['rows'])}] carried passing four-section fit {rid}", flush=True)
        else:
            print(f"[{index}/{len(manifest['rows'])}] refit {rid}", flush=True)
            low = [0.998, 2 * np.pi * 20 / sr, 0.994, 2 * np.pi * 20 / sr]
            high = [0.90, 2 * np.pi * 18000 / sr, 0.95, 2 * np.pi * 18000 / sr]
            warm = base["parameters"] + low + high
            fit = fitter.fit_curve(ROOT / row["analysis_csv"], sr, index * 7919, warm)
            fit["pass"] = pass_gate(fit, sr)
            fit["source_model"] = "six-section fit with low/high edge initial poles and zeros"
        fit.update({"id": rid, "sample_rate_hz": sr, "configuration": row["configuration"],
                    "source": row["analysis_csv"], "method_version": 2})
        by_id[rid] = fit
        results = [by_id[item["id"]] for item in manifest["rows"] if item["id"] in by_id]
        OUT.write_text(json.dumps({"schema": "altair-eq.stable-sos-fit/3", "sections": 6,
                                   "method": "six stable biquads capped at radius 0.999; nodes not reusable under the cap are refit with edge-focused initial poles and zeros",
                                   "manifest": str(MANIFEST.relative_to(ROOT)).replace("\\", "/"),
                                   "results": results}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"  {'PASS' if fit['pass'] else 'FAIL'} mag={fit['band_max_magnitude_error_db']} "
              f"phase={fit['max_phase_error_deg']:.3f} deg", flush=True)
    print(f"summary: {sum(x['pass'] for x in results)}/{len(results)} pass -> {OUT}")


if __name__ == "__main__":
    main()
