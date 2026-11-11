#!/usr/bin/env python3
"""Probe six-section fits on the worst four-section failures."""
import json
from pathlib import Path

import fit_pultec_lf_stable_sos as fitter


ROOT = Path(__file__).resolve().parents[2]
FIT_SET = ROOT / "measurements/results/pultec_lf/stable_sos_fits.json"
OUT = ROOT / "measurements/results/pultec_lf/stable_sos_six_section_probe.json"


def main():
    rows = json.loads(FIT_SET.read_text(encoding="utf-8"))["results"]
    failures = sorted((row for row in rows if not row["pass"]),
                      key=lambda row: row["max_phase_error_deg"], reverse=True)[:5]
    fitter.SECTIONS = 6
    results = []
    for row in failures:
        print(f"\nCASE {row['id']}", flush=True)
        sr = row["sample_rate_hz"]
        low = [0.998, 2 * 3.141592653589793 * 20 / sr,
               0.994, 2 * 3.141592653589793 * 20 / sr]
        high = [0.90, 2 * 3.141592653589793 * 18000 / sr,
                0.95, 2 * 3.141592653589793 * 18000 / sr]
        warm = row["parameters"] + low + high
        result = fitter.fit_curve(ROOT / row["source"], row["sample_rate_hz"], 65000,
                                  warm)
        tolerances = {"20-100": 0.20, "100-1000": 0.15,
                      f"1000-{min(18000, row['sample_rate_hz'] / 2):g}": 0.10}
        passed = (result["max_pole_radius"] < 1 and result["max_phase_error_deg"] <= 2 and
                  all(result["band_max_magnitude_error_db"][band] <= tol
                      for band, tol in tolerances.items()))
        result.update({"id": row["id"], "sample_rate_hz": row["sample_rate_hz"],
                       "pass": bool(passed), "seed": 65000,
                       "method": "six-section fit initialized from the four-section result and edge-focused poles/zeros"})
        results.append(result)
        print(f"{'PASS' if passed else 'FAIL'} mag={result['band_max_magnitude_error_db']} "
              f"phase={result['max_phase_error_deg']:.3f} deg", flush=True)
    OUT.write_text(json.dumps({"schema": "altair-eq.stable-sos-probe/1", "sections": 6,
                               "source_fit_set": str(FIT_SET.relative_to(ROOT)).replace("\\", "/"),
                               "results": results}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"summary: {sum(x['pass'] for x in results)}/{len(results)} pass -> {OUT}")


if __name__ == "__main__":
    main()
