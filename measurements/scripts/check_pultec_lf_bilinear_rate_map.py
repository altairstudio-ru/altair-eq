#!/usr/bin/env python3
"""Probe bilinear mapping of digital roots between measured sample rates."""
import csv
import json
from pathlib import Path

import numpy as np

import fit_pultec_lf_stable_sos as fitter


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "measurements/results/pultec_lf/lowlevel_analysis_manifest.json"
FITS = ROOT / "measurements/results/pultec_lf/stable_sos_six_section_fits.json"
OUT = ROOT / "measurements/results/pultec_lf/sample_rate_bilinear_probe.json"


def key(row):
    p = row["configuration"]
    return (int(p["lf_cps_hz"]), float(p["lf_boost_ui"] or 0), float(p["lf_atten_ui"] or 0))


def map_root(radius, angle, source_rate, target_rate):
    z = radius * np.exp(1j * angle)
    analog = 2 * source_rate * (z - 1) / (z + 1)
    mapped = (2 * target_rate + analog) / (2 * target_rate - analog)
    return float(abs(mapped)), float(abs(np.angle(mapped)))


def map_parameters(parameters, source_rate, target_rate):
    out = list(parameters)
    for offset in range(1, len(out), 4):
        rp, tp, rz, tz = out[offset:offset + 4]
        out[offset:offset + 2] = map_root(rp, tp, source_rate, target_rate)
        out[offset + 2:offset + 4] = map_root(rz, tz, source_rate, target_rate)
    return out


def main():
    fitter.SECTIONS = 6
    rows = json.loads(MANIFEST.read_text(encoding="utf-8"))["rows"]
    fitted = json.loads(FITS.read_text(encoding="utf-8"))["results"]
    fits44 = {key(row): row for row in fitted if row["sample_rate_hz"] == 44100}
    results = []
    for row in rows:
        sr = int(row["sample_rate_hz"])
        if sr == 44100:
            continue
        source = fits44.get(key(row))
        if source is None:
            raise SystemExit(f"no 44.1 kHz fit for {row['id']}")
        parameters = map_parameters(source["parameters"], 44100.0, float(sr))
        with (ROOT / row["analysis_csv"]).open(newline="", encoding="utf-8") as stream:
            csv_rows = list(csv.DictReader(stream))
        freq = np.array([float(x["freq_hz"]) for x in csv_rows])
        target_db = np.array([float(x["magnitude_db"]) for x in csv_rows])
        target_phase = np.deg2rad([float(x["phase_deg"]) for x in csv_rows])
        target = 10 ** (target_db / 20) * np.exp(1j * target_phase)
        omega = 2 * np.pi * freq / sr
        model = fitter.response(np.asarray(parameters), omega)
        # Only adjust scalar gain; pole and zero locations stay mapped.
        gain_correction = float(np.mean(np.log(np.maximum(np.abs(target), 1e-12) /
                                               np.maximum(np.abs(model), 1e-12))))
        parameters[0] += gain_correction
        model = fitter.response(np.asarray(parameters), omega)
        mag_error = 20 * np.log10(np.maximum(np.abs(model), 1e-12)) - target_db
        phase_error = np.angle(model * np.conj(target)) * 180 / np.pi
        bands = {}
        for lower, upper in ((20, 100), (100, 1000), (1000, 18000)):
            mask = (freq >= lower) & (freq < upper if upper < 18000 else freq <= upper)
            bands[f"{lower}-{upper}"] = float(np.max(np.abs(mag_error[mask])))
        passed = (bands["20-100"] <= .20 and bands["100-1000"] <= .15 and
                  bands["1000-18000"] <= .10 and np.max(np.abs(phase_error)) <= 2)
        results.append({"id": row["id"], "sample_rate_hz": sr,
                        "source_fit_id": source["id"], "pass": bool(passed),
                        "band_max_magnitude_error_db": bands,
                        "max_phase_error_deg": float(np.max(np.abs(phase_error)))})
        print(f"{row['id']}: {'PASS' if passed else 'FAIL'} mag={bands} "
              f"phase={np.max(np.abs(phase_error)):.3f} deg", flush=True)
    OUT.write_text(json.dumps({"schema": "altair-eq.sample-rate-bilinear-probe/1",
                               "method": "bilinear map roots and refit scalar gain",
                               "source_fit": str(FITS.relative_to(ROOT)).replace("\\", "/"),
                               "results": results}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"summary: {sum(x['pass'] for x in results)}/{len(results)} pass -> {OUT}")


if __name__ == "__main__":
    main()
