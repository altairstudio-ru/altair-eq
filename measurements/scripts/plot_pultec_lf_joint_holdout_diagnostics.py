#!/usr/bin/env python3
"""Plot saved measured-vs-predicted joint LF holdout responses (no new renders)."""
import csv
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from scipy.interpolate import RBFInterpolator

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "measurements/results/pultec_lf/lowlevel_analysis_manifest.json"
COARSE = ROOT / "measurements/results/pultec_lf/joint_grid_44k1_coarse_manifest.json"
INTEGER = ROOT / "measurements/results/pultec_lf/joint_grid_44k1_integer_manifest.json"
AXIS = ROOT / "measurements/results/pultec_lf/axis_integer_8sos_fits.json"
FLAT_FIT = ROOT / "measurements/results/pultec_lf/flat_reference_fit.json"
FLAT = ROOT / "measurements/results/pultec_lf/level_sweep_control_v2/flat-m36-44k1-sweep.csv"
JOINT_FITS = ROOT / "measurements/results/pultec_lf/joint_residual_sos_basis_fits_axisbase_8axis_6sec.json"
OUT = ROOT / "measurements/results/pultec_lf/joint_holdout_diagnostic_curves.png"
SR = 44100
CASES = [(20, 9, 5), (30, 6, 9), (60, 5, 7), (100, 9, 6)]


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
        rp, tp, rz, tz = parameters[1 + index * 4:5 + index * 4]
        h *= (1 - 2 * rz * np.cos(tz) * q + rz * rz * q * q) / (1 - 2 * rp * np.cos(tp) * q + rp * rp * q * q)
    return h


def main():
    targets = {}
    for row in json.loads(BASE.read_text(encoding="utf-8"))["rows"]:
        if row["sample_rate_hz"] == SR:
            c = row["configuration"]
            targets[(c["lf_cps_hz"], float(c["lf_boost_ui"]), float(c["lf_atten_ui"]))] = curve(ROOT / row["analysis_csv"])
    for manifest in (COARSE, INTEGER):
        for row in json.loads(manifest.read_text(encoding="utf-8"))["rows"].values():
            if row.get("status") == "complete":
                targets[(row["lf_cps_hz"], float(row["lf_boost_ui"]), float(row["lf_atten_ui"]))] = curve(ROOT / row["analysis_csv"])

    flat_freq, flat_measured, _ = curve(FLAT)
    flat_params = json.loads(FLAT_FIT.read_text(encoding="utf-8"))["result"]["parameters"]
    axis_rows = json.loads(AXIS.read_text(encoding="utf-8"))["results"]
    axis = {}
    for row in axis_rows:
        c = row["configuration"]
        axis[(c["lf_cps_hz"], float(c["lf_boost_ui"]), float(c["lf_atten_ui"]))] = row
    fit_rows = json.loads(JOINT_FITS.read_text(encoding="utf-8"))["results"]
    by_cps = {}
    for row in fit_rows:
        by_cps.setdefault(int(row["key"][0]), {})[tuple(row["key"])] = row

    predictions = {}
    metrics = []
    for cps, boost, atten in CASES:
        fits = by_cps[cps]
        coords, values = [], []
        for b in range(0, 11, 2):
            for a in range(0, 11, 2):
                if (b, a) in ((8, 2), (2, 8)):
                    continue
                if b == 0 or a == 0:
                    residual = np.zeros_like(flat_measured)
                else:
                    item = fits[(cps, float(b), float(a))]
                    residual = response(item["parameters"], flat_freq, item["sections"])
                coords.append([b / 2.0, a / 2.0])
                values.append(np.r_[residual.real, residual.imag])
        rbf = RBFInterpolator(np.asarray(coords), np.asarray(values), kernel="cubic", degree=1)
        freq, target, target_db = targets[(cps, float(boost), float(atten))]
        vector = rbf([[boost / 2, atten / 2]])[0]
        residual = vector[:len(freq)] + 1j * vector[len(freq):]
        hb = response(axis[(cps, float(boost), 0.0)]["parameters"], freq, 8)
        ha = response(axis[(cps, 0.0, float(atten))]["parameters"], freq, 8)
        hflat = response(flat_params, freq, 6)
        pred = hb + ha - hflat + residual
        error_db = 20 * np.log10(np.maximum(np.abs(pred), 1e-12)) - target_db
        error_phase = np.unwrap(np.angle(pred * np.conj(target))) * 180 / np.pi
        band = (freq >= 1000) & (freq <= 18000)
        band_indices = np.flatnonzero(band)
        worst_hf = band_indices[int(np.argmax(np.abs(error_db[band])))]
        predictions[(cps, boost, atten)] = (freq, target_db, 20 * np.log10(np.maximum(np.abs(pred), 1e-12)), error_db, error_phase)
        metrics.append({"cps": cps, "boost": boost, "atten": atten,
                        "max_error_db_1k_18k": float(np.max(np.abs(error_db[band]))),
                        "worst_hf_frequency_hz": float(freq[worst_hf]),
                        "signed_error_at_worst_hf_db": float(error_db[worst_hf]),
                        "max_phase_error_deg": float(np.max(np.abs(error_phase)))})

    fig, axes = plt.subplots(len(CASES), 3, figsize=(16, 13), sharex=True)
    fig.suptitle("Pultec LF joint holdout: measured vs six-section residual model\nSaved 44.1 kHz sweeps; no new renders", fontsize=15)
    for row_i, (cps, boost, atten) in enumerate(CASES):
        freq, target_db, predicted_db, error_db, error_phase = predictions[(cps, boost, atten)]
        axes[row_i, 0].semilogx(freq, target_db, label="Measured", lw=1.5)
        axes[row_i, 0].semilogx(freq, predicted_db, label="Model", lw=1.2, ls="--")
        axes[row_i, 0].set_ylabel(f"CPS {cps}\nB{boost}/A{atten}\nMagnitude (dB)")
        axes[row_i, 0].grid(True, which="both", alpha=.22)
        if row_i == 0:
            axes[row_i, 0].legend(loc="best")
        axes[row_i, 1].semilogx(freq, error_db, color="#b44", lw=1.1)
        axes[row_i, 1].axhline(.1, color="black", ls=":", lw=.8)
        axes[row_i, 1].axhline(-.1, color="black", ls=":", lw=.8)
        axes[row_i, 1].axvspan(1000, 18000, color="#e7a74f", alpha=.10)
        axes[row_i, 1].set_ylabel("Magnitude error (dB)")
        axes[row_i, 1].grid(True, which="both", alpha=.22)
        axes[row_i, 2].semilogx(freq, error_phase, color="#526c9a", lw=1.0)
        axes[row_i, 2].axhline(2, color="black", ls=":", lw=.8)
        axes[row_i, 2].axhline(-2, color="black", ls=":", lw=.8)
        axes[row_i, 2].set_ylabel("Phase error (deg)")
        axes[row_i, 2].grid(True, which="both", alpha=.22)
        axes[row_i, 1].text(.99, .94, f"max |e| 1–18 kHz = {metrics[row_i]['max_error_db_1k_18k']:.3f} dB",
                            transform=axes[row_i, 1].transAxes, ha="right", va="top", fontsize=8)
    for ax in axes[-1, :]:
        ax.set_xlabel("Frequency (Hz)")
        ax.set_xlim(20, 18000)
    axes[0, 1].set_title("Error (dotted = ±0.10 dB high-band limit)")
    axes[0, 2].set_title("Phase error (dotted = ±2° limit)")
    fig.tight_layout(rect=(0, 0, 1, .95))
    fig.savefig(OUT, dpi=160)
    csv_path = OUT.with_suffix(".csv")
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["cps", "boost", "atten", "freq_hz", "measured_db", "predicted_db", "magnitude_error_db", "phase_error_deg"])
        for (cps, boost, atten), values in predictions.items():
            freq, target_db, predicted_db, error_db, error_phase = values
            writer.writerows(zip([cps] * len(freq), [boost] * len(freq), [atten] * len(freq),
                                 freq, target_db, predicted_db, error_db, error_phase))
    (OUT.with_suffix(".json")).write_text(json.dumps({"cases": metrics, "model": str(JOINT_FITS.relative_to(ROOT)),
                                                       "axis": str(AXIS.relative_to(ROOT)), "sample_rate_hz": SR}, indent=2) + "\n",
                                                    encoding="utf-8")
    print(json.dumps(metrics, indent=2))
    print(f"plot: {OUT}")


if __name__ == "__main__":
    main()
