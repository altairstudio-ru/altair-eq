#!/usr/bin/env python3
"""Check physical-frequency root scaling of the 44.1 kHz fits at other rates."""
import csv
import json
from pathlib import Path

import numpy as np

import fit_pultec_lf_stable_sos as fitter


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "measurements/results/pultec_lf/lowlevel_analysis_manifest.json"
FITS = ROOT / "measurements/results/pultec_lf/stable_sos_six_section_fits.json"
OUT = ROOT / "measurements/results/pultec_lf/sample_rate_scaling_probe.json"


def parameter_key(row):
    p = row["configuration"]
    return (int(p["lf_cps_hz"]), float(p["lf_boost_ui"] or 0), float(p["lf_atten_ui"] or 0))


def scale_roots(parameters, source_rate, target_rate):
    ratio = source_rate / target_rate
    scaled = list(parameters)
    for offset in range(1, len(scaled), 4):
        rp, tp, rz, tz = scaled[offset:offset + 4]
        scaled[offset:offset + 4] = [rp ** ratio, tp * ratio, rz ** ratio, tz * ratio]
    return scaled


def analyze(path, sr, parameters):
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    freq = np.array([float(x["freq_hz"]) for x in rows])
    target_db = np.array([float(x["magnitude_db"]) for x in rows])
    target_phase = np.deg2rad([float(x["phase_deg"]) for x in rows])
    target = 10 ** (target_db / 20) * np.exp(1j * target_phase)
    actual = fitter.response(np.asarray(parameters), 2 * np.pi * freq / sr)
    mag_error = 20 * np.log10(np.maximum(np.abs(actual), 1e-12)) - target_db
    phase_error = np.angle(actual * np.conj(target)) * 180 / np.pi
    bands = {}
    for lower, upper in ((20, 100), (100, 1000), (1000, 18000)):
        mask = (freq >= lower) & (freq < upper if upper < 18000 else freq <= upper)
        bands[f"{lower}-{upper}"] = float(np.max(np.abs(mag_error[mask])))
    return {"band_max_magnitude_error_db": bands,
            "max_phase_error_deg": float(np.max(np.abs(phase_error))),
            "rms_phase_error_deg": float(np.sqrt(np.mean(phase_error ** 2)))}


def main():
    fitter.SECTIONS = 6
    rows = json.loads(MANIFEST.read_text(encoding="utf-8"))["rows"]
    fitted = json.loads(FITS.read_text(encoding="utf-8"))["results"]
    fits44 = {parameter_key(row): row for row in fitted if row["sample_rate_hz"] == 44100}
    results = []
    for row in rows:
        sr = int(row["sample_rate_hz"])
        if sr == 44100:
            continue
        source = fits44.get(parameter_key(row))
        if source is None:
            raise SystemExit(f"no 44.1 kHz fit for {row['id']}")
        parameters = scale_roots(source["parameters"], 44100.0, float(sr))
        metrics = analyze(ROOT / row["analysis_csv"], sr, parameters)
        tol = metrics["band_max_magnitude_error_db"]
        passed = (tol["20-100"] <= 0.20 and tol["100-1000"] <= 0.15 and
                  tol["1000-18000"] <= 0.10 and metrics["max_phase_error_deg"] <= 2.0)
        results.append({"id": row["id"], "sample_rate_hz": sr,
                        "source_fit_id": source["id"], "pass": passed, **metrics})
        print(f"{row['id']}: {'PASS' if passed else 'FAIL'} mag={tol} "
              f"phase={metrics['max_phase_error_deg']:.3f} deg", flush=True)
    OUT.write_text(json.dumps({"schema": "altair-eq.sample-rate-scaling-probe/1",
                               "method": "scale pole/zero angles and log-radii by source_rate/target_rate",
                               "source_fit": str(FITS.relative_to(ROOT)).replace("\\", "/"),
                               "results": results}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"summary: {sum(x['pass'] for x in results)}/{len(results)} pass -> {OUT}")


if __name__ == "__main__":
    main()
