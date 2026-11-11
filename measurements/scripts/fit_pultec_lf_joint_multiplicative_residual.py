#!/usr/bin/env python3
"""Fit a causal correction factor to the joint response relative to fitted axes."""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "measurements/scripts"))
import fit_pultec_lf_joint_residual_basis as fitter

AXIS = ROOT / "measurements/results/pultec_lf/axis_integer_8sos_fits.json"
FLAT_FIT = ROOT / "measurements/results/pultec_lf/flat_reference_fit.json"
OUT = ROOT / "measurements/results/pultec_lf/joint_multiplicative_sos_fits_6sec.json"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sections", type=int, default=6)
    parser.add_argument("--starts", type=int, default=2)
    parser.add_argument("--max-nfev", type=int, default=1400)
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else ROOT / args.output
    data = {}
    for row in json.loads(fitter.BASE.read_text(encoding="utf-8"))["rows"]:
        if row["sample_rate_hz"] != fitter.SR:
            continue
        c = row["configuration"]
        data[(c["lf_cps_hz"], float(c["lf_boost_ui"]), float(c["lf_atten_ui"]))] = fitter.curve(ROOT / row["analysis_csv"])
    for manifest in (fitter.COARSE, fitter.INTEGER):
        for row in json.loads(manifest.read_text(encoding="utf-8"))["rows"].values():
            if row.get("status") == "complete":
                data[(row["lf_cps_hz"], float(row["lf_boost_ui"]), float(row["lf_atten_ui"]))] = fitter.curve(ROOT / row["analysis_csv"])
    axes = {}
    for row in json.loads(AXIS.read_text(encoding="utf-8"))["results"]:
        c = row["configuration"]
        if row["sample_rate_hz"] == fitter.SR:
            axes[(c["lf_cps_hz"], float(c["lf_boost_ui"]), float(c["lf_atten_ui"]))] = row
    flat_params = json.loads(FLAT_FIT.read_text(encoding="utf-8"))["result"]["parameters"]
    saved = json.loads(output.read_text(encoding="utf-8"))["results"] if output.exists() else []
    fits = {tuple(r["key"]): r for r in saved}
    for cps in (20, 30, 60, 100):
        for b in range(2, 11, 2):
            for a in range(2, 11, 2):
                if (b, a) in ((8, 2), (2, 8)):
                    continue
                key = (cps, float(b), float(a))
                if key in fits:
                    continue
                freq, joint, _ = data[key]
                omega = 2 * np.pi * freq / fitter.SR
                hb = fitter.response(axes[(cps, float(b), 0.0)]["parameters"], omega, 8)
                ha = fitter.response(axes[(cps, 0.0, float(a))]["parameters"], omega, 8)
                hf = fitter.response(flat_params, omega, 6)
                base = hb + ha - hf
                if np.min(np.abs(base)) < 1e-5:
                    raise SystemExit(f"near-zero baseline at {key}")
                target = joint / base
                print(f"CPS={cps} Boost={b} Atten={a}; correction RMS={np.sqrt(np.mean(np.abs(target-1)**2)):.6g}", flush=True)
                fit = fitter.fit_residual(freq, target, args.sections,
                                          cps * 100000 + b * 1000 + a * 37,
                                          args.starts, args.max_nfev)
                fit.update({"key": list(key), "sample_rate_hz": fitter.SR,
                            "sections": args.sections, "representation": "multiplicative correction ratio"})
                fits[key] = fit
                output.write_text(json.dumps({"schema": "altair-eq.pultec-lf-joint-multiplicative-sos/1",
                                              "fit_settings": {"sections": args.sections, "starts": args.starts,
                                                                "max_nfev": args.max_nfev,
                                                                "axis_baseline": str(AXIS.relative_to(ROOT)).replace("\\", "/")},
                                              "results": list(fits.values())}, indent=2) + "\n", encoding="utf-8")
                print(f"  normalized complex RMS={fit['normalized_complex_rms']:.5g}; max |error|={fit['max_abs_error']:.5g}", flush=True)
    print(f"multiplicative fits {len(fits)} -> {output}")


if __name__ == "__main__":
    main()
