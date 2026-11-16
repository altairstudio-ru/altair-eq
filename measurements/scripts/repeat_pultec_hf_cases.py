"""Повтор двух верхнечастотных промахов и ближайших опор без изменения модели."""
import csv
import json
import subprocess
from pathlib import Path
from tempfile import mkdtemp

from measure_pultec_lf_joint_grid import CPS_NORMALIZED, PLUGIN, RENDERER, ROOT
from validate_pultec_total_reserve import DIRECTORY, sha256
from validate_pultec_lf_causal_bank_extended_band import load_rows


def main():
    anchors = DIRECTORY.parent / "edges_v4_anchors"
    meta = json.loads((anchors / "manifest.json").read_text())
    rows = load_rows()
    folder = Path(mkdtemp(prefix="repeat_v4_hf_", dir=DIRECTORY.parent))
    print(folder, flush=True)
    with (folder / "audit.csv").open("w", newline="") as out:
        writer = csv.writer(out)
        writer.writerow(["cps","boost","atten","source_sha256","original","old_sha256","new_sha256","latency","byte_equal"])
        for c,b,a in [(30,9,4),(30,9.125,4.125),(100,10,1),(100,10,1.125)]:
            if (c,b,a) in rows:
                r = rows[c,b,a]
                source, src_hash = ROOT / r["input"], r["input_sha256"]
                old, old_hash = ROOT / r["output"], r["output_sha256"]
            else:
                r = next(r for r in meta["rows"] if (r["c"],r["b"],r["a"]) == (c,b,a))
                source, src_hash = ROOT / meta["source"]["path"], meta["source"]["sha256"]
                old, old_hash = anchors / r["wav"], r["sha256"]
            if sha256(source) != src_hash or sha256(old) != old_hash:
                raise ValueError("Исходный WAV отличается от манифеста")
            wav = folder / f"c{c}-b{b}-a{a}.wav"
            subprocess.run([RENDERER,PLUGIN,source,wav,f"0={CPS_NORMALIZED[c]}",
                            f"1={b/10}",f"2={a/10}","8=0.5","9=0.5","10=0.5","11=0",
                            "--require-latency=86"],check=True)
            latency = json.loads(wav.with_suffix(".json").read_text())["latency_samples_reported"]
            if latency != 86:
                raise ValueError("Неверная задержка")
            digest = sha256(wav)
            writer.writerow([c,b,a,src_hash,old,old_hash,digest,latency,digest == old_hash])
            out.flush()
            print(c,b,a,"identical:",digest == old_hash,flush=True)


if __name__ == "__main__":
    main()
