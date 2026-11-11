#!/usr/bin/env python3
"""Fit stable six-section basis filters for measured even-grid joint LF settings."""
import json
import sys
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "measurements/scripts"))
import fit_pultec_lf_stable_sos as fitter

BASE = ROOT / "measurements/results/pultec_lf/lowlevel_analysis_manifest.json"
COARSE = ROOT / "measurements/results/pultec_lf/joint_grid_44k1_coarse_manifest.json"
OUT = ROOT / "measurements/results/pultec_lf/joint_even_sos_fits.json"
SR = 44100


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sections", type=int, default=6)
    parser.add_argument("--output", type=Path, default=OUT)
    parser.add_argument("--refine", action="store_true",
                        help="use three starts and a larger evaluation budget for every node")
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else ROOT / args.output
    fitter.SECTIONS = args.sections
    fitter.MAX_POLE_RADIUS = .999
    rows = {}
    for row in json.loads(BASE.read_text(encoding="utf-8"))["rows"]:
        if row["sample_rate_hz"] != SR:
            continue
        cfg = row["configuration"]
        b, a = float(cfg["lf_boost_ui"]), float(cfg["lf_atten_ui"])
        if b > 0 and a > 0 and b.is_integer() and a.is_integer() and int(b) % 2 == 0 and int(a) % 2 == 0:
            rows[(cfg["lf_cps_hz"], b, a)] = row["analysis_csv"]
    for row in json.loads(COARSE.read_text(encoding="utf-8"))["rows"].values():
        b, a = float(row["lf_boost_ui"]), float(row["lf_atten_ui"])
        if b > 0 and a > 0 and int(b) % 2 == 0 and int(a) % 2 == 0:
            rows[(row["lf_cps_hz"], b, a)] = row["analysis_csv"]
    nodes = [(cps, float(b), float(a), path)
             for cps in (20, 30, 60, 100)
             for b in range(2, 11, 2) for a in range(2, 11, 2)
             if (b, a) not in ((8, 2), (2, 8))
             if (cps, float(b), float(a)) in rows
             for path in (rows[(cps, float(b), float(a))],)]
    fitted = {}
    if output.exists():
        saved = json.loads(output.read_text(encoding="utf-8"))
        fitted = {tuple(row["key"]): row for row in saved["results"]}
    warm_by_cps = {}
    for index, (cps, boost, atten, source) in enumerate(nodes, 1):
        key = (cps, boost, atten)
        if key in fitted and fitted[key]["pass"] and not args.refine:
            warm_by_cps[cps] = fitted[key]["parameters"]
            continue
        retry = key in fitted
        print(f"[{index}/{len(nodes)}] {'retry ' if retry else ''}CPS={cps} "
              f"Boost={boost:g} Atten={atten:g}", flush=True)
        if retry or args.refine:
            fit = fitter.fit_curve(ROOT / source, SR,
                                   int(cps * 100000 + boost * 1000 + atten * 37 + 1000000),
                                   fitted[key]["parameters"] if retry else warm_by_cps.get(cps),
                                   max_starts=3, max_nfev=1200)
        else:
            fit = fitter.fit_curve(ROOT / source, SR,
                                   int(cps * 100000 + boost * 1000 + atten * 37),
                                   warm_by_cps.get(cps), max_starts=1, max_nfev=350)
        fit.update({"key": list(key), "sample_rate_hz": SR, "source": source,
                    "pass": (fit["max_pole_radius"] < 1.0
                             and fit["max_phase_error_deg"] <= 2.0
                             and fit["band_max_magnitude_error_db"]["20-100"] <= .20
                             and fit["band_max_magnitude_error_db"]["100-1000"] <= .15
                             and fit["band_max_magnitude_error_db"]["1000-18000"] <= .10)})
        fitted[key] = fit
        warm_by_cps[cps] = fit["parameters"]
        payload = {"schema": "altair-eq.pultec-lf-joint-even-sos-fits/1",
                   "sample_rate_hz": SR, "sections": args.sections, "max_pole_radius": .999,
                   "fit_limits": {"max_starts": 3 if (retry or args.refine) else 1,
                                  "max_nfev": 1200 if (retry or args.refine) else 350},
                   "results": list(fitted.values())}
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"  {'PASS' if fit['pass'] else 'FIT-ONLY'} pole={fit['max_pole_radius']:.6f} "
              f"phase={fit['max_phase_error_deg']:.2f}", flush=True)
    payload = {"schema": "altair-eq.pultec-lf-joint-even-sos-fits/1",
               "sample_rate_hz": SR, "sections": args.sections, "max_pole_radius": .999,
               "fit_limits": {"max_starts": 3 if args.refine else 1,
                              "max_nfev": 1200 if args.refine else 350},
               "results": list(fitted.values())}
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"joint SOS basis fits: {sum(bool(r['pass']) for r in fitted.values())}/{len(nodes)} full-fit PASS -> {output}")


if __name__ == "__main__":
    main()
