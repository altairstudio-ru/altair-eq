#!/usr/bin/env python3
"""Check whether low-rank interaction modes admit compact stable SOS fits."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "measurements/scripts"))
import fit_pultec_lf_stable_sos as fitter

MODE_DIR = ROOT / "measurements/results/pultec_lf/joint_residual_svd_modes"
OUT = ROOT / "measurements/results/pultec_lf/joint_residual_svd_mode_fits.json"
SR = 44100


def main():
    fitter.SECTIONS = 6
    fitter.MAX_POLE_RADIUS = .999
    results = []
    for cps in (20, 30, 60, 100):
        manifest = json.loads((MODE_DIR / f"cps{cps}-modes.json").read_text(encoding="utf-8"))
        for row in manifest["modes"]:
            source = ROOT / row["source"]
            rid = row["id"]
            print(f"fitting {rid}", flush=True)
            fit = fitter.fit_curve(source, SR, cps * 1000 + int(rid[-2:]),
                                   max_starts=3, max_nfev=1200)
            fit["pass"] = (fit["max_pole_radius"] < 1.0
                           and fit["max_phase_error_deg"] <= 2.0
                           and fit["band_max_magnitude_error_db"]["20-100"] <= .20
                           and fit["band_max_magnitude_error_db"]["100-1000"] <= .15
                           and fit["band_max_magnitude_error_db"]["1000-18000"] <= .10)
            results.append({**row, **fit, "sample_rate_hz": SR, "source": row["source"],
                            "model_sections": fitter.SECTIONS})
            OUT.write_text(json.dumps({"schema": "altair-eq.pultec-lf-residual-svd-mode-fits/1",
                                       "results": results}, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
            print(f"  {'PASS' if fit['pass'] else 'FAIL'}; pole={fit['max_pole_radius']:.6f}; "
                  f"phase={fit['max_phase_error_deg']:.3f} deg", flush=True)
    print(f"compact stable-mode fits: {sum(r['pass'] for r in results)}/{len(results)} pass")


if __name__ == "__main__":
    main()
