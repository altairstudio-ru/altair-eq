#!/usr/bin/env python3
"""Localize saved joint-model error across controls and measured axis fits."""
import csv
import json
import sys
import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from scipy.interpolate import RBFInterpolator

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "measurements/scripts"))
import plot_pultec_lf_joint_holdout_diagnostics as model

BASE = ROOT / "measurements/results/pultec_lf/lowlevel_analysis_manifest.json"
COARSE = ROOT / "measurements/results/pultec_lf/joint_grid_44k1_coarse_manifest.json"
INTEGER = ROOT / "measurements/results/pultec_lf/joint_grid_44k1_integer_manifest.json"
AXIS = ROOT / "measurements/results/pultec_lf/axis_integer_8sos_fits.json"
JOINT_FITS = ROOT / "measurements/results/pultec_lf/joint_residual_sos_basis_fits_axisbase_8axis_6sec.json"
FLAT_FIT = ROOT / "measurements/results/pultec_lf/flat_reference_fit.json"
FLAT = ROOT / "measurements/results/pultec_lf/level_sweep_control_v2/flat-m36-44k1-sweep.csv"
OUT = ROOT / "measurements/results/pultec_lf/joint_error_distribution"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fits", type=Path, default=JOINT_FITS,
                        help="joint residual SOS fit manifest")
    parser.add_argument("--output", type=Path, default=OUT,
                        help="output path prefix for CSV, JSON, and PNG")
    args = parser.parse_args()
    fits_path = args.fits if args.fits.is_absolute() else ROOT / args.fits
    out = args.output if args.output.is_absolute() else ROOT / args.output
    targets = {}
    for row in json.loads(BASE.read_text(encoding="utf-8"))["rows"]:
        if row["sample_rate_hz"] == model.SR:
            c = row["configuration"]
            targets[(c["lf_cps_hz"], float(c["lf_boost_ui"]), float(c["lf_atten_ui"]))] = model.curve(ROOT / row["analysis_csv"])
    for name in (COARSE, INTEGER):
        for row in json.loads(name.read_text(encoding="utf-8"))["rows"].values():
            if row.get("status") == "complete":
                targets[(row["lf_cps_hz"], float(row["lf_boost_ui"]), float(row["lf_atten_ui"]))] = model.curve(ROOT / row["analysis_csv"])

    flat_freq, flat_measured, _ = model.curve(FLAT)
    flat_params = json.loads(FLAT_FIT.read_text(encoding="utf-8"))["result"]["parameters"]
    axis_rows = json.loads(AXIS.read_text(encoding="utf-8"))["results"]
    axis = {}
    for row in axis_rows:
        c = row["configuration"]
        axis[(c["lf_cps_hz"], float(c["lf_boost_ui"]), float(c["lf_atten_ui"]))] = row
    joint_rows = json.loads(fits_path.read_text(encoding="utf-8"))["results"]
    by_cps = {}
    for row in joint_rows:
        by_cps.setdefault(int(row["key"][0]), {})[tuple(row["key"])] = row

    holdout_errors = []
    holdout_ids = []
    train_errors = []
    train_ids = []
    for cps, fits in by_cps.items():
        coords, values = [], []
        for b in range(0, 11, 2):
            for a in range(0, 11, 2):
                if (b, a) in ((8, 2), (2, 8)):
                    continue
                if b == 0 or a == 0:
                    residual = np.zeros_like(flat_measured)
                else:
                    item = fits[(cps, float(b), float(a))]
                    residual = model.response(item["parameters"], flat_freq, item["sections"])
                coords.append([b / 2, a / 2])
                values.append(np.r_[residual.real, residual.imag])
        rbf = RBFInterpolator(coords, values, kernel="cubic", degree=1)
        for (fit_cps, boost, atten), fit in fits.items():
            if fit_cps != cps:
                continue
            freq, target, target_db = targets[(cps, float(boost), float(atten))]
            hb = model.response(axis[(cps, float(boost), 0.0)]["parameters"], freq, 8)
            ha = model.response(axis[(cps, 0.0, float(atten))]["parameters"], freq, 8)
            hflat = model.response(flat_params, freq, 6)
            residual = model.response(fit["parameters"], freq, fit["sections"])
            pred = hb + ha - hflat + residual
            train_errors.append(20 * np.log10(np.maximum(np.abs(pred), 1e-12)) - target_db)
            train_ids.append((cps, boost, atten))
        for (target_cps, boost, atten), (freq, target, target_db) in targets.items():
            if target_cps != cps or boost == 0 or atten == 0:
                continue
            if boost % 2 == 0 and atten % 2 == 0 and (boost, atten) not in ((8, 2), (2, 8)):
                continue
            vec = rbf([[boost / 2, atten / 2]])[0]
            residual = vec[:len(freq)] + 1j * vec[len(freq):]
            hb = model.response(axis[(cps, boost, 0.0)]["parameters"], freq, 8)
            ha = model.response(axis[(cps, 0.0, atten)]["parameters"], freq, 8)
            hflat = model.response(flat_params, freq, 6)
            pred = hb + ha - hflat + residual
            err_db = 20 * np.log10(np.maximum(np.abs(pred), 1e-12)) - target_db
            holdout_errors.append(err_db)
            holdout_ids.append((cps, boost, atten))

    holdout_errors = np.asarray(holdout_errors)
    train_errors = np.asarray(train_errors)
    freq = flat_freq
    axis_errors = []
    for row in axis_rows:
        c = row["configuration"]
        key = (c["lf_cps_hz"], float(c["lf_boost_ui"]), float(c["lf_atten_ui"]))
        f, target, db = targets[key]
        pred = model.response(row["parameters"], f, 8)
        axis_errors.append(20 * np.log10(np.maximum(np.abs(pred), 1e-12)) - db)
    axis_errors = np.asarray(axis_errors)

    records = []
    for idx, hz in enumerate(freq):
        records.append({"freq_hz": float(hz),
                        "holdout_median_signed_db": float(np.median(holdout_errors[:, idx])),
                        "holdout_median_abs_db": float(np.median(np.abs(holdout_errors[:, idx]))),
                        "holdout_p90_abs_db": float(np.percentile(np.abs(holdout_errors[:, idx]), 90)),
                        "holdout_max_abs_db": float(np.max(np.abs(holdout_errors[:, idx]))),
                        "train_median_signed_db": float(np.median(train_errors[:, idx])),
                        "train_median_abs_db": float(np.median(np.abs(train_errors[:, idx]))),
                        "train_p90_abs_db": float(np.percentile(np.abs(train_errors[:, idx]), 90)),
                        "train_max_abs_db": float(np.max(np.abs(train_errors[:, idx]))),
                        "axis_median_signed_db": float(np.median(axis_errors[:, idx])),
                        "axis_median_abs_db": float(np.median(np.abs(axis_errors[:, idx]))),
                        "axis_p90_abs_db": float(np.percentile(np.abs(axis_errors[:, idx]), 90)),
                        "axis_max_abs_db": float(np.max(np.abs(axis_errors[:, idx])))})
    out.with_suffix(".csv").parent.mkdir(parents=True, exist_ok=True)
    with out.with_suffix(".csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader(); writer.writerows(records)

    ids = np.where((freq >= 1000) & (freq <= 18000))[0]
    worst = sorted(ids, key=lambda i: records[i]["holdout_p90_abs_db"], reverse=True)[:10]
    bands = ((20, 100, .20), (100, 1000, .15), (1000, 18000, .10))
    band_summary = {}
    for lo, hi, tolerance in bands:
        mask = (freq >= lo) & (freq <= hi)
        overall = {
            "train_curves_exceeding_band_limit": int(np.sum(np.max(np.abs(train_errors[:, mask]), axis=1) > tolerance)),
            "holdout_curves_exceeding_band_limit": int(np.sum(np.max(np.abs(holdout_errors[:, mask]), axis=1) > tolerance)),
            "train_curve_count": len(train_ids), "holdout_curve_count": len(holdout_ids),
            "tolerance_db": tolerance}
        by_cps = {}
        for cps in (20, 30, 60, 100):
            ti = [i for i, item in enumerate(train_ids) if item[0] == cps]
            hi_idx = [i for i, item in enumerate(holdout_ids) if item[0] == cps]
            by_cps[str(cps)] = {
                "train_curves_exceeding_band_limit": int(np.sum(np.max(np.abs(train_errors[ti][:, mask]), axis=1) > tolerance)),
                "holdout_curves_exceeding_band_limit": int(np.sum(np.max(np.abs(holdout_errors[hi_idx][:, mask]), axis=1) > tolerance)),
                "train_curve_count": len(ti), "holdout_curve_count": len(hi_idx)}
        band_summary[f"{lo}-{hi}"] = {**overall, "by_cps": by_cps}
    summary = {"holdout_count": len(holdout_ids), "train_count": len(train_ids), "axis_count": len(axis_rows),
               "band_summary": band_summary, "top_holdout_p90_bins": [records[i] for i in worst]}
    out.with_suffix(".json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    fig, ax = plt.subplots(figsize=(11, 6))
    ax.semilogx(freq, [r["holdout_median_signed_db"] for r in records], label="Holdout median signed error")
    ax.semilogx(freq, [r["train_median_signed_db"] for r in records], label="Training median signed error")
    ax.semilogx(freq, [r["axis_median_signed_db"] for r in records], label="Axis-fit median signed error")
    ax.semilogx(freq, [r["holdout_p90_abs_db"] for r in records], label="Holdout 90th percentile |error|")
    ax.semilogx(freq, [r["train_p90_abs_db"] for r in records], label="Training 90th percentile |error|")
    ax.semilogx(freq, [r["axis_p90_abs_db"] for r in records], label="Axis-fit 90th percentile |error|")
    ax.axvline(17494.907789, color="#b44", ls=":", label="17 494.9 Hz bin")
    ax.axhline(.1, color="black", ls="--", lw=.8, label="±0.10 dB high-band limit")
    ax.axhspan(0, .1, color="#8c8", alpha=.08)
    ax.set(xlim=(20, 18000), xlabel="Frequency (Hz)", ylabel="Magnitude error (dB)",
           title=f"Joint model error distribution: {len(holdout_ids)} holdouts, {len(train_ids)} fitted nodes")
    ax.grid(True, which="both", alpha=.25); ax.legend(ncol=2); fig.tight_layout()
    fig.savefig(out.with_suffix(".png"), dpi=160)
    print(json.dumps(summary, indent=2))
    print(f"plot: {out.with_suffix('.png')}")


if __name__ == "__main__":
    main()
