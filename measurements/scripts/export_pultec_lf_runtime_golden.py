#!/usr/bin/env python3
"""Export stable measured-fit models and measured frequency samples for C++ runtime tests."""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIT = ROOT / "measurements/results/pultec_lf/stable_sos_six_section_fits_r0999.json"
FLAT_FIT = ROOT / "measurements/results/pultec_lf/flat_reference_fit.json"
FLAT_CSV = ROOT / "measurements/results/pultec_lf/level_sweep_control_v2/flat-m36-44k1-sweep.csv"
OUT = ROOT / "tests/golden/PultecLfRuntimeGolden.h"
FREQUENCIES = (20.0, 100.0, 1000.0, 10000.0, 18000.0)


def samples(path):
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    indexed = {float(row["freq_hz"]): row for row in rows}
    result = []
    for frequency in FREQUENCIES:
        row = indexed[frequency]
        result.append((frequency, float(row["magnitude_db"]), float(row["phase_deg"])))
    return result


def array(name, values):
    body = ",\n        ".join(f"{value:.17g}" for value in values)
    return f"inline constexpr PultecLf::RootParameters {name} {{{{\n        {body}\n}}}};"


def goldens(name, values):
    body = ",\n    ".join("{" + ", ".join(f"{v:.17g}" for v in row) + "}" for row in values)
    return f"inline constexpr std::array<Sample, {len(values)}> {name} {{{{\n    {body}\n}}}};"


def main():
    fits = json.loads(FIT.read_text(encoding="utf-8"))["results"]
    target = next(row for row in fits if row["sample_rate_hz"] == 44100
                  and row["configuration"]["lf_cps_hz"] == 60
                  and row["configuration"]["lf_boost_ui"] == 6
                  and row["configuration"]["lf_atten_ui"] == 0)
    boost_source = next(row["source"] for row in fits if row["id"] == target["id"])
    flat_parameters = json.loads(FLAT_FIT.read_text(encoding="utf-8"))["result"]["parameters"]
    content = """#pragma once
#include <array>
#include \"PultecLf.h\"
namespace PultecLfGolden
{
struct Sample { double frequency, magnitudeDb, phaseDegrees; };
"""
    content += array("flatModel", flat_parameters) + "\n"
    content += array("boostModel", target["parameters"]) + "\n"
    content += goldens("flat", samples(FLAT_CSV)) + "\n"
    content += goldens("boostCps60B6", samples(ROOT / boost_source)) + "\n"
    content += "}\n"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(content, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} from measured data and capped six-section fits")


if __name__ == "__main__":
    main()
