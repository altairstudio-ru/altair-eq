#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Генератор сетки замеров Pultec EQP-1A LF (этап 4, docs/WORK_PLAN_PULTEC_MVP.md).

Выход: measurements/grid/pultec_lf_grid.json и measurements/grid/pultec_lf_grid.csv.
Одна строка сетки = одно рендер-задание (конфигурация плагина + сигнал + sample rate).

Значения ручек — в UI-единицах (0-10); индексы параметров и нормализованные
значения маппятся на этапе 3 после dump_fx_params.lua (см. паспорт эталона).

Запуск: python measurements/scripts/build_grid.py
"""
import csv
import io
import json
import os
from datetime import datetime, timezone

# Флаги обновляются после дампа параметров (этап 2):
KNOB_CONTINUOUS = False        # True -> добавить промежуточные ступени 0.5
OUTPUT_GAIN_CONFIRMED = True   # подтверждено vst3-дампом 09.11.2026: OFF, -12.0..+12.0 dB
EQ_IN_CONFIRMED = True         # подтверждено vst3-дампом 09.11.2026: Enable Out/In

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
GRID_DIR = os.path.join(ROOT, "measurements", "grid")

CPS = [20, 30, 60, 100]
KNOBS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
TRICK_PAIRS = [(2, 2), (4, 4), (6, 6), (8, 8), (10, 10), (10, 5), (5, 10), (8, 2), (2, 8)]
SR_MAIN = 44100
SR_REDUCED = [48000, 96000]
SR_REDUCED_CPS = [30, 100]
SR_REDUCED_KNOBS = [3, 7, 10]
SR_REDUCED_TRICK_PAIRS = [(6, 6), (10, 5), (5, 10)]
LEVEL_FREQS = [50, 100, 1000]
LEVELS_DBFS = [-36, -24, -18, -12, -6]
LEVEL_CONFIGS = [
    ("flat", None, 0, 0),
    ("char60b6a4", 60, 6, 4),
]
IMD_LEVELS_DBFS = [-12, -6]
OUTPUT_GAIN_VALUES_DB = [-12.0, -6.0, 0.0, 6.0, 12.0]

STATIC_SIGNALS = ["impulse", "sweep_log"]

SIGNALS = {
    "impulse": {
        "type": "impulse",
        "description": "unit impulse, 200 ms leading silence, 5 s total, peak 0 dBFS",
        "duration_s": 5.0,
        "level_dbfs": 0.0,
    },
    "sweep_log": {
        "type": "log_sweep",
        "description": "log sweep 1 Hz .. 0.45*SR, 15 s, 50 ms fades, -12 dBFS",
        "duration_s": 15.0,
        "level_dbfs": -12.0,
    },
    "sine_50": {
        "type": "sine",
        "frequency_hz": 50,
        "description": "sine 50 Hz, 10 s; level defines grid row (level_dbfs)",
        "duration_s": 10.0,
        "level_dbfs": None,
    },
    "sine_100": {
        "type": "sine",
        "frequency_hz": 100,
        "description": "sine 100 Hz, 10 s; level defines grid row (level_dbfs)",
        "duration_s": 10.0,
        "level_dbfs": None,
    },
    "sine_1000": {
        "type": "sine",
        "frequency_hz": 1000,
        "description": "sine 1000 Hz, 10 s; level defines grid row (level_dbfs)",
        "duration_s": 10.0,
        "level_dbfs": None,
    },
    "twotone_50_1000": {
        "type": "two_tone",
        "frequencies_hz": [50, 1000],
        "amplitude_ratio": "4:1 (50 Hz : 1000 Hz)",
        "description": "two-tone IMD 50 Hz + 1000 Hz, 10 s; level defines grid row",
        "duration_s": 10.0,
        "level_dbfs": None,
    },
}

SR_TOKEN = {44100: "44k1", 48000: "48k", 96000: "96k"}
SIG_TOKEN = {
    "impulse": "imp",
    "sweep_log": "swp",
    "sine_50": "s50",
    "sine_100": "s100",
    "sine_1000": "s1k",
    "twotone_50_1000": "tt",
}


def plugin_state(cps=None, boost=0, atten=0, eq_in=True, host_bypass=False,
                 fx_present=True, output_gain=None):
    return {
        "fx_present": fx_present,
        "host_bypass": host_bypass,
        "eq_in": eq_in,
        "lf_cps_hz": cps,
        "lf_boost_ui": boost,
        "lf_atten_ui": atten,
        "output_gain_ui": output_gain,
    }


def make_row(row_id, group, priority, conditional, sample_rate_hz, plugin,
             signal, purpose, level_dbfs=None):
    return {
        "id": row_id,
        "group": group,
        "priority": priority,
        "conditional": conditional,
        "sample_rate_hz": sample_rate_hz,
        "plugin": plugin,
        "signal": signal,
        "level_dbfs": level_dbfs,
        "purpose": purpose,
    }


def knobs_list():
    values = list(KNOBS)
    if KNOB_CONTINUOUS:
        values = sorted(set(values + [k + 0.5 for k in values if k + 0.5 <= 10]))
    return values


def fmt_knob(value):
    return "{:04.1f}".format(value).replace(".", "")


def add_static(rows, group, priority, sample_rate_hz, cps, boost, atten, purpose):
    srt = SR_TOKEN[sample_rate_hz]
    for signal in STATIC_SIGNALS:
        sgt = SIG_TOKEN[signal]
        row_id = "{}-{}-b{}-a{}-{}-{}".format(group, cps, fmt_knob(boost), fmt_knob(atten), srt, sgt)
        rows.append(make_row(row_id, group, priority, False, sample_rate_hz,
                             plugin_state(cps=cps, boost=boost, atten=atten), signal, purpose))


def build_rows():
    rows = []

    # 1. Boost only: 4 CPS x ручка 1..10, Atten = 0.
    for cps in CPS:
        for knob in knobs_list():
            add_static(rows, "boost_only", 1, SR_MAIN, cps, knob, 0,
                       "Static magnitude/phase: LF boost grid (atten=0)")

    # 2. Atten only: симметрично.
    for cps in CPS:
        for knob in knobs_list():
            add_static(rows, "atten_only", 1, SR_MAIN, cps, 0, knob,
                       "Static magnitude/phase: LF attenuation grid (boost=0)")

    # 3. Boost+Atten одновременно на том же CPS ("low-end trick").
    for cps in CPS:
        for boost, atten in TRICK_PAIRS:
            add_static(rows, "boost_atten_trick", 1, SR_MAIN, cps, boost, atten,
                       "Simultaneous boost+atten interaction at same CPS")

    # 4. Служебные состояния против transparent.
    for signal in STATIC_SIGNALS:
        sgt = SIG_TOKEN[signal]
        rows.append(make_row("svc-transparent-{}-{}".format(SR_TOKEN[SR_MAIN], sgt),
                             "service", 1, False, SR_MAIN,
                             plugin_state(fx_present=False), signal,
                             "Reference path without plugin (null/calibration)"))
        rows.append(make_row("svc-flat-{}-{}".format(SR_TOKEN[SR_MAIN], sgt),
                             "service", 1, False, SR_MAIN,
                             plugin_state(cps=None, boost=0, atten=0), signal,
                             "All knobs zero, EQ in: path coloration check"))
        rows.append(make_row("svc-hostbypass-{}-{}".format(SR_TOKEN[SR_MAIN], sgt),
                             "service", 1, False, SR_MAIN,
                             plugin_state(host_bypass=True), signal,
                             "Host bypass: must equal transparent"))
        rows.append(make_row("svc-eqoff-{}-{}".format(SR_TOKEN[SR_MAIN], sgt),
                             "service", 1, not EQ_IN_CONFIRMED, SR_MAIN,
                             plugin_state(eq_in=False), signal,
                             "EQ IN off (conditional until dump confirms switch)"))

    # 5. Выходной Gain: подтверждён дампом (OFF, -12.0..+12.0 dB, шаг 0.1).
    for gain_db in OUTPUT_GAIN_VALUES_DB:
        token = "{}{}".format("p" if gain_db > 0 else ("m" if gain_db < 0 else "z"), abs(gain_db))
        rows.append(make_row("og-{}-{}-{}".format(token, SR_TOKEN[SR_MAIN], SIG_TOKEN["sweep_log"]),
                             "output_gain", 2, not OUTPUT_GAIN_CONFIRMED, SR_MAIN,
                             plugin_state(cps=60, boost=6, atten=4, output_gain=gain_db),
                             "sweep_log",
                             "Output gain influence at characteristic config (60 CPS, B6/A4)"))

    # 6. Уровневая зависимость: синусы 50/100/1000 Hz x уровни x flat/char.
    for cfg_name, cps, boost, atten in LEVEL_CONFIGS:
        for freq in LEVEL_FREQS:
            signal = "sine_{}".format(freq) if freq != 1000 else "sine_1000"
            for level in LEVELS_DBFS:
                row_id = "lvl-{}-{}-{}db".format(cfg_name, SIG_TOKEN[signal], abs(level))
                rows.append(make_row(row_id, "level_dependence", 2, False, SR_MAIN,
                                     plugin_state(cps=cps, boost=boost, atten=atten),
                                     signal,
                                     "Level dependence: gain vs input level, harmonics",
                                     level_dbfs=level))
        for level in IMD_LEVELS_DBFS:
            row_id = "imd-{}-{}db".format(cfg_name, abs(level))
            rows.append(make_row(row_id, "level_dependence", 2, False, SR_MAIN,
                                 plugin_state(cps=cps, boost=boost, atten=atten),
                                 "twotone_50_1000",
                                 "Two-tone IMD at characteristic/flat config",
                                 level_dbfs=level))

    # 7. Сокращённая сетка на 48 и 96 kHz (SR-зависимость / oversampling).
    for sample_rate in SR_REDUCED:
        for cps in SR_REDUCED_CPS:
            for knob in SR_REDUCED_KNOBS:
                add_static(rows, "sr_reduced", 2, sample_rate, cps, knob, 0,
                           "SR dependence check: boost")
                add_static(rows, "sr_reduced", 2, sample_rate, cps, 0, knob,
                           "SR dependence check: atten")
            for boost, atten in SR_REDUCED_TRICK_PAIRS:
                add_static(rows, "sr_reduced", 2, sample_rate, cps, boost, atten,
                           "SR dependence check: boost+atten trick")
        for signal in STATIC_SIGNALS:
            rows.append(make_row("svc-flat-{}-{}".format(SR_TOKEN[sample_rate], SIG_TOKEN[signal]),
                                 "sr_reduced", 2, False, sample_rate,
                                 plugin_state(cps=None, boost=0, atten=0), signal,
                                 "Flat reference at alternate SR"))

    return rows


def write_outputs(rows):
    os.makedirs(GRID_DIR, exist_ok=True)
    json_path = os.path.join(GRID_DIR, "pultec_lf_grid.json")
    csv_path = os.path.join(GRID_DIR, "pultec_lf_grid.csv")

    grid = {
        "schema": "altair-eq.measurement-grid/1",
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "plan_ref": "docs/WORK_PLAN_PULTEC_MVP.md, stage 4",
        "passport_ref": "measurements/passports/reference_instance.json",
        "status": "proposed - renders not performed",
        "flags": {
            "KNOB_CONTINUOUS": KNOB_CONTINUOUS,
            "OUTPUT_GAIN_CONFIRMED": OUTPUT_GAIN_CONFIRMED,
            "EQ_IN_CONFIRMED": EQ_IN_CONFIRMED,
        },
        "notes": [
            "One row = one render job (plugin config + signal + sample rate).",
            "Knob values are UI units (0-10); normalized mapping comes from dump_fx_params.lua at stage 3.",
            "Static signal level -12 dBFS is a working hypothesis; may be revised after level-dependence results.",
            "Every render must carry a passport per docs/RESEARCH_EQ_MARKET.md section 8.",
            "conditional=true rows wait for stage-2 dump confirmation before rendering.",
        ],
        "signals": SIGNALS,
        "row_count": len(rows),
        "rows": rows,
    }
    with io.open(json_path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(grid, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    fieldnames = ["id", "group", "priority", "conditional", "sample_rate_hz",
                  "fx_present", "host_bypass", "eq_in", "lf_cps_hz", "lf_boost_ui",
                  "lf_atten_ui", "output_gain_ui", "signal", "level_dbfs", "purpose"]
    with io.open(csv_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            flat = {
                "id": row["id"],
                "group": row["group"],
                "priority": row["priority"],
                "conditional": row["conditional"],
                "sample_rate_hz": row["sample_rate_hz"],
                "signal": row["signal"],
                "level_dbfs": row["level_dbfs"],
                "purpose": row["purpose"],
            }
            flat.update(row["plugin"])
            writer.writerow(flat)

    return json_path, csv_path


def main():
    rows = build_rows()
    json_path, csv_path = write_outputs(rows)

    ids = [r["id"] for r in rows]
    duplicates = len(ids) - len(set(ids))

    by_group = {}
    conditional = 0
    for row in rows:
        by_group[row["group"]] = by_group.get(row["group"], 0) + 1
        if row["conditional"]:
            conditional += 1

    print("Grid written:")
    print("  " + json_path)
    print("  " + csv_path)
    print("Rows: {} (conditional: {}, duplicate ids: {})".format(len(rows), conditional, duplicates))
    for group in sorted(by_group):
        print("  {:18s} {:4d}".format(group, by_group[group]))
    print("Flags: KNOB_CONTINUOUS={}, OUTPUT_GAIN_CONFIRMED={}, EQ_IN_CONFIRMED={}".format(
        KNOB_CONTINUOUS, OUTPUT_GAIN_CONFIRMED, EQ_IN_CONFIRMED))


if __name__ == "__main__":
    main()
