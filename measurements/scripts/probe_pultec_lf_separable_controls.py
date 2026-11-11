#!/usr/bin/env python3
"""Check whether combined LF response is the product of separately measured boost/attenuation."""
import csv
import json
from pathlib import Path

import numpy as np

import fit_pultec_lf_stable_sos as fitter

ROOT = Path(__file__).resolve().parents[2]
FITS = ROOT / "measurements/results/pultec_lf/stable_sos_six_section_fits_r0999.json"
OUT = ROOT / "measurements/results/pultec_lf/separable_controls_probe.json"


def target(row):
    with (ROOT / row["source"]).open(newline="", encoding="utf-8") as stream:
        data = list(csv.DictReader(stream))
    f = np.array([float(x["freq_hz"]) for x in data])
    mag = np.array([float(x["magnitude_db"]) for x in data])
    phase = np.deg2rad([float(x["phase_deg"]) for x in data])
    return f, 10 ** (mag / 20) * np.exp(1j * phase)


def main():
    fitter.SECTIONS = 6
    rows = json.loads(FITS.read_text(encoding="utf-8"))["results"]
    index = {}
    for row in rows:
        c = row["configuration"]
        index[(row["sample_rate_hz"], c["lf_cps_hz"], c["lf_boost_ui"], c["lf_atten_ui"])] = row
    results = []
    for mixed in rows:
        c = mixed["configuration"]
        b, a = c["lf_boost_ui"], c["lf_atten_ui"]
        if not b or not a:
            continue
        sr, cps = mixed["sample_rate_hz"], c["lf_cps_hz"]
        boost = index.get((sr, cps, b, 0))
        atten = index.get((sr, cps, 0, a))
        if boost is None or atten is None:
            results.append({"id": mixed["id"], "pass": None, "reason": "missing axis node"})
            continue
        freq, ref = target(mixed)
        omega = 2 * np.pi * freq / sr
        prediction = fitter.response(boost["parameters"], omega) * fitter.response(atten["parameters"], omega)
        mag_err = 20 * np.log10(np.abs(prediction / ref))
        phase_err = np.angle(prediction * np.conj(ref)) * 180 / np.pi
        upper = min(18000, sr / 2)
        bands = {}
        for lo, hi in ((20, 100), (100, 1000), (1000, upper)):
            mask = (freq >= lo) & (freq <= hi if hi == upper else freq < hi)
            bands[f"{lo}-{hi:g}"] = float(np.max(np.abs(mag_err[mask])))
        passed = (bands["20-100"] <= .2 and bands["100-1000"] <= .15
                  and bands[f"1000-{upper:g}"] <= .1 and np.max(np.abs(phase_err)) <= 2)
        results.append({"id": mixed["id"], "sample_rate_hz": sr, "lf_cps_hz": cps,
                        "lf_boost_ui": b, "lf_atten_ui": a, "pass": passed,
                        "band_max_magnitude_error_db": bands,
                        "max_phase_error_deg": float(np.max(np.abs(phase_err)))})
    OUT.write_text(json.dumps({"schema": "altair-eq.separable-controls-probe/1",
                               "method": "multiply separately fitted boost-only and attenuation-only transfer functions",
                               "source_fit": str(FITS.relative_to(ROOT)).replace("\\", "/"),
                               "results": results}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tested = [x for x in results if x.get("pass") is not None]
    print(f"separable product: {sum(x['pass'] for x in tested)}/{len(tested)} pass; "
          f"{sum(x.get('pass') is None for x in results)} missing-axis cases")
    print(f"details: {OUT}")


if __name__ == "__main__":
    main()
