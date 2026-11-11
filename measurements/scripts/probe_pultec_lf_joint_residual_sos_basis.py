#!/usr/bin/env python3
"""Evaluate direct SOS fits of the joint interaction residual on withheld controls."""
import csv
import json
import argparse
from pathlib import Path

import numpy as np
from scipy.interpolate import RBFInterpolator

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "measurements/results/pultec_lf/lowlevel_analysis_manifest.json"
COARSE = ROOT / "measurements/results/pultec_lf/joint_grid_44k1_coarse_manifest.json"
INTEGER = ROOT / "measurements/results/pultec_lf/joint_grid_44k1_integer_manifest.json"
FITS = ROOT / "measurements/results/pultec_lf/joint_residual_sos_basis_fits.json"
AXIS_FITS = ROOT / "measurements/results/pultec_lf/stable_sos_six_section_fits_r0999.json"
FLAT_FIT = ROOT / "measurements/results/pultec_lf/flat_reference_fit.json"
FLAT = ROOT / "measurements/results/pultec_lf/level_sweep_control_v2/flat-m36-44k1-sweep.csv"
OUT = ROOT / "measurements/results/pultec_lf/joint_residual_sos_basis_probe.json"
SR = 44100


def curve(path):
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    freq = np.array([float(r["freq_hz"]) for r in rows])
    db = np.array([float(r["magnitude_db"]) for r in rows])
    phase = np.deg2rad([float(r["phase_deg"]) for r in rows])
    return freq, 10 ** (db / 20) * np.exp(1j * phase), db


def response(parameters, freq, sections):
    q = np.exp(-1j * 2 * np.pi * freq / SR)
    h = np.full(q.shape, np.exp(parameters[0]), dtype=np.complex128)
    for index in range(sections):
        rp, tp, rz, tz = parameters[1 + index * 4: 5 + index * 4]
        h *= (1 - 2 * rz * np.cos(tz) * q + rz * rz * q * q) / (1 - 2 * rp * np.cos(tp) * q + rp * rp * q * q)
    return h


def fit_response(parameters, freq):
    return response(parameters, freq, (len(parameters) - 1) // 4)


def metric(pred, target, db, freq):
    mag = 20 * np.log10(np.maximum(np.abs(pred), 1e-12)) - db
    phase = np.angle(pred * np.conj(target)) * 180 / np.pi
    bands = {}
    for lo, hi in ((20, 100), (100, 1000), (1000, 18000)):
        m = (freq >= lo) & (freq < hi if hi < 18000 else freq <= hi)
        bands[f"{lo}-{hi}"] = float(np.max(np.abs(mag[m])))
    p = float(np.max(np.abs(phase)))
    passed = (bands["20-100"] <= .2 and bands["100-1000"] <= .15
              and bands["1000-18000"] <= .1 and p <= 2)
    return {"pass": bool(passed), "band_max_magnitude_error_db": bands,
            "max_phase_error_deg": p}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fit-axes", action="store_true",
                        help="replace measured axis responses with their stable SOS fits")
    parser.add_argument("--fits", type=Path, default=FITS,
                        help="residual basis fit manifest")
    parser.add_argument("--axis-fits", type=Path, default=AXIS_FITS,
                        help="axis SOS fit manifest used with --fit-axes")
    args = parser.parse_args()
    fit_path = args.fits if args.fits.is_absolute() else ROOT / args.fits
    axis_fit_path = args.axis_fits if args.axis_fits.is_absolute() else ROOT / args.axis_fits
    targets = {}
    for row in json.loads(BASE.read_text(encoding="utf-8"))["rows"]:
        if row["sample_rate_hz"] == SR:
            c = row["configuration"]
            targets[(c["lf_cps_hz"], float(c["lf_boost_ui"]), float(c["lf_atten_ui"]))] = curve(ROOT / row["analysis_csv"])
    for manifest in (COARSE, INTEGER):
        for row in json.loads(manifest.read_text(encoding="utf-8"))["rows"].values():
            if row.get("status") == "complete":
                targets[(row["lf_cps_hz"], float(row["lf_boost_ui"]), float(row["lf_atten_ui"]))] = curve(ROOT / row["analysis_csv"])
    flat = curve(FLAT)
    axis_fits = {}
    flat_parameters = None
    if args.fit_axes:
        for row in json.loads(axis_fit_path.read_text(encoding="utf-8"))["results"]:
            if row["sample_rate_hz"] != SR:
                continue
            c = row["configuration"]
            axis_fits[(c["lf_cps_hz"], float(c["lf_boost_ui"]), float(c["lf_atten_ui"]))] = row
        flat_parameters = json.loads(FLAT_FIT.read_text(encoding="utf-8"))["result"]["parameters"]
    fit_rows = json.loads(fit_path.read_text(encoding="utf-8"))["results"]
    by_cps = {}
    for row in fit_rows:
        by_cps.setdefault(int(row["key"][0]), {})[tuple(row["key"])] = row
    results = []
    for cps, fits in by_cps.items():
        freq = flat[0]
        coords, values = [], []
        for b in range(0, 11, 2):
            for a in range(0, 11, 2):
                if (b, a) in ((8, 2), (2, 8)):
                    continue
                if b == 0 or a == 0:
                    residual = np.zeros_like(flat[1])
                else:
                    fit = fits.get((cps, float(b), float(a)))
                    if fit is None:
                        raise SystemExit(f"missing residual SOS fit for {(cps,b,a)}")
                    residual = response(fit["parameters"], freq, fit["sections"])
                coords.append([b / 2.0, a / 2.0])
                values.append(np.concatenate([residual.real, residual.imag]))
        model = RBFInterpolator(np.asarray(coords), np.asarray(values), kernel="cubic", degree=1)
        for b in range(1, 11):
            for a in range(1, 11):
                if b % 2 == 0 and a % 2 == 0 and (b, a) not in ((8, 2), (2, 8)):
                    continue
                key = (cps, float(b), float(a))
                if key not in targets:
                    continue
                freq, target, db = targets[key]
                residual_value = model(np.array([[b / 2.0, a / 2.0]]))[0]
                residual = residual_value[:len(freq)] + 1j * residual_value[len(freq):]
                if args.fit_axes:
                    hb = fit_response(axis_fits[(cps, float(b), 0.0)]["parameters"], freq)
                    ha = fit_response(axis_fits[(cps, 0.0, float(a))]["parameters"], freq)
                    hflat = fit_response(flat_parameters, freq)
                else:
                    hb = targets[(cps, float(b), 0.0)][1]
                    ha = targets[(cps, 0.0, float(a))][1]
                    hflat = flat[1]
                base = hb + ha - hflat
                results.append({"id": f"cps{cps}-b{b:02d}-a{a:02d}",
                                **metric(base + residual, target, db, freq)})
    summary = {str(cps): {"pass": sum(r["pass"] for r in results if r["id"].startswith(f"cps{cps}-")),
                          "total": sum(r["id"].startswith(f"cps{cps}-") for r in results),
                          "max_phase_error_deg": max(r["max_phase_error_deg"] for r in results if r["id"].startswith(f"cps{cps}-")),
                          "max_band_errors_db": {band: max(r["band_max_magnitude_error_db"][band] for r in results if r["id"].startswith(f"cps{cps}-"))
                                                  for band in ("20-100", "100-1000", "1000-18000")}}
               for cps in by_cps}
    output = (OUT.with_name(f"{fit_path.stem}_{axis_fit_path.stem}_probe.json")
              if args.fit_axes else OUT.with_name(f"{fit_path.stem}_probe.json"))
    output.write_text(json.dumps({"schema": "altair-eq.pultec-lf-joint-residual-sos-basis-probe/1",
                               "method": "RBF-weighted sums of directly fitted stable SOS interaction residuals",
                               "axis_responses": str(axis_fit_path.relative_to(ROOT)).replace("\\", "/") if args.fit_axes else "measured complex responses",
                               "residual_basis_fits": str(fit_path.relative_to(ROOT)).replace("\\", "/"),
                               "sample_rate_hz": SR, "summary": summary, "results": results},
                              ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"details: {output}")


if __name__ == "__main__":
    main()
