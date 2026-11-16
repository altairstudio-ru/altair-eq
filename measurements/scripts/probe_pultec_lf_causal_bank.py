"""Fixed-pole parallel bank. Fit uses axes, flat and 23 joint nodes per CPS."""
import argparse
import csv
import json
from pathlib import Path

import numpy as np
from scipy.interpolate import RBFInterpolator

from probe_pultec_lf_joint_polar_svd import BASE, COARSE, FLAT, INTEGER, ROOT, SR, curve

OUT = BASE.parent / "causal_bank"
CPS = (20, 30, 60, 100)
TRAIN = [(b, a) for b in range(2, 11, 2) for a in range(2, 11, 2)
         if (b, a) not in ((8, 2), (2, 8))]
LIMIT = np.array([.20, .15, .10, 2.0])
NAMES = ["low_db", "mid_db", "high_db", "phase_deg"]


def paths():
    result = {}
    for manifest in (BASE, COARSE, INTEGER):
        rows = json.loads(manifest.read_text(encoding="utf-8"))["rows"]
        for r in rows if isinstance(rows, list) else rows.values():
            if r["sample_rate_hz"] != SR or r.get("status", "complete") != "complete":
                continue
            c = r.get("configuration", r)
            result[c["lf_cps_hz"], c["lf_boost_ui"], c["lf_atten_ui"]] = ROOT / r["analysis_csv"]
    return result


def basis(f, poles):
    q = np.exp(-2j * np.pi * f[:, None] / SR)
    # Real and imaginary parts of the causal complex-pole impulse response.
    pos = (1 - abs(poles)) / (1 - poles * q)
    neg = (1 - abs(poles)) / (1 - poles.conj() * q)
    return np.column_stack([q ** np.arange(48), (pos + neg) / 2, (pos - neg) / (2j)])


def errors(f, prediction, target):
    ratio = prediction / target
    mag = abs(20 * np.log10(abs(ratio)))
    bands = [(f >= 20) & (f < 100), (f >= 100) & (f < 1000), (f >= 1000) & (f <= 18000)]
    return np.array([*(mag[m].max() for m in bands),
                     abs(np.angle(ratio[(f >= 20) & (f <= 18000)], deg=True)).max()])


def impulse_check(poles, grid):
    # Fractional controls 8.5 / 2.5, bilinear midpoint.
    weights = grid[8:10, 2:4].mean(axis=(0, 1))
    samples = np.zeros(65536)
    state = 1 - abs(poles) + 0j
    for i in range(len(samples)):
        samples[i] = weights[48:96] @ state.real + weights[96:] @ state.imag
        state *= poles
    samples[:48] += weights[:48]
    freq = np.fft.rfftfreq(len(samples), 1 / SR)[::16]
    delta = abs(np.fft.rfft(samples)[::16] - basis(freq, poles) @ weights).max()
    if not delta < 1e-8:
        raise ValueError(f"Impulse check failed: {delta}")
    print("fractional impulse FFT max complex error", delta)


def fit(f, data, flat):
    centers = np.geomspace(12, 21000, 48)
    poles = np.exp((-0.32 + 1j) * 2 * np.pi * centers / SR)
    design = basis(f, poles)
    guard = basis(np.linspace(18500, SR / 2, 32), poles)

    def project(target):
        relative = design / target[:, None]
        # Relative real error dominates dB, imaginary error dominates phase.
        matrix = np.vstack([relative.real, .45 * relative.imag, .002 * guard.real,
                            .002 * guard.imag, .0001 * np.eye(design.shape[1])])
        rhs = np.r_[np.ones(len(f)), np.zeros(len(f)), np.full(len(guard), .002),
                    np.zeros(len(guard) + design.shape[1])]
        return np.linalg.lstsq(matrix, rhs, rcond=None)[0]

    flat_w = project(flat)
    tables = {}
    for cps in CPS:
        boost = [flat_w] + [project(data(cps, b, 0)) for b in range(1, 11)]
        atten = [flat_w] + [project(data(cps, 0, a)) for a in range(1, 11)]
        axes = [(0, a) for a in range(0, 11, 2)] + [(b, 0) for b in range(2, 11, 2)]
        residual = [project(data(cps, b, a)) - boost[b] - atten[a] + flat_w for b, a in TRAIN]
        interpolator = RBFInterpolator(TRAIN + axes, np.vstack([residual, np.zeros((len(axes), len(flat_w)))]),
                                       kernel="cubic", degree=1)
        grid = np.empty((11, 11, len(flat_w)))
        for b, a in np.ndindex(11, 11):
            grid[b, a] = boost[b] + atten[a] - flat_w
            if b and a:
                grid[b, a] += interpolator([[b, a]])[0]
        tables[str(cps)] = grid.tolist()
    return {"sample_rate": SR, "layout": "48 FIR taps, real states, imaginary states",
            "pole_real": poles.real.tolist(), "pole_imag": poles.imag.tolist(), "tables": tables}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--train-only", action="store_true")
    args = parser.parse_args()
    files = paths()
    f, flat, _ = curve(FLAT)

    def data(cps, b, a):
        measured_f, target, _ = curve(files[cps, b, a])
        if not np.array_equal(f, measured_f):
            raise ValueError("Inconsistent frequency grid")
        return target

    OUT.mkdir(exist_ok=True)
    model_path = OUT / "model.json"
    model_path.write_text(json.dumps(fit(f, data, flat), separators=(",", ":")), encoding="utf-8")
    model = json.loads(model_path.read_text(encoding="utf-8"))
    poles = np.array(model["pole_real"]) + 1j * np.array(model["pole_imag"])
    design = basis(f, poles)
    print("max pole radius", max(abs(poles)), "buffer delay (samples)", 0)
    dense_f = np.linspace(0, SR / 2, 8193)
    dense_design = basis(dense_f, poles)
    rows = []
    for cps in CPS:
        grid = np.asarray(model["tables"][str(cps)])
        impulse_check(poles, grid)
        dense_db = 20 * np.log10(abs(dense_design @ grid.reshape(121, -1).T))
        coarse_db = 20 * np.log10(abs(design @ grid.reshape(121, -1).T))
        in_band = (dense_f >= 20) & (dense_f <= 18000)
        envelope_error = max(np.max(abs(dense_db[in_band, i] - np.interp(
            dense_f[in_band], f, coarse_db[:, i]))) for i in range(121))
        print(cps, "dense deviation from linear interpolation of model samples (dB)",
              round(envelope_error, 4), "peak above 18 kHz (dB)",
              round(dense_db[dense_f > 18000].max(), 4), "max adjacent weight step",
              round(max(abs(np.diff(grid, axis=i)).max() for i in (0, 1)), 4))
        for label, coords in [("train", TRAIN), ("holdout", [(b, a) for b in range(1, 11)
                              for a in range(1, 11) if (b, a) not in TRAIN])]:
            if args.train_only and label == "holdout":
                continue
            stats = []
            for b, a in coords:
                err = errors(f, design @ grid[b, a], data(cps, b, a))
                stats.append(err)
                rows.append([cps, label, b, a, *err])
            values = np.asarray(stats)
            ok = values <= LIMIT
            print(cps, label, "pass", ok.all(axis=1).sum(), "bands+phase", ok.sum(axis=0),
                  "max", values.max(axis=0).round(4), "p90", np.percentile(values, 90, axis=0).round(4))
    with (OUT / ("train.csv" if args.train_only else "errors.csv")).open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["cps", "split", "boost", "atten", *NAMES])
        writer.writerows(rows)


if __name__ == "__main__":
    main()
