"""Print one chunk of out/samples.jsonl compactly, as the brief for writing its prompts.

Rows are grouped by leaf. Write the prompts of a chunk into l4_raw/chunk_<NNN>.txt.

usage: python scripts/show.py --project DIR [--chunk K] [--size N] [--hide VALUE ...]
"""
import argparse
import json
from pathlib import Path

ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
ap.add_argument("--project", required=True, help="project directory; every file the script reads or writes is inside it")
ap.add_argument("--chunk", type=int, default=0, help="chunk number (0-based)")
ap.add_argument("--size", type=int, default=100, help="rows per chunk")
ap.add_argument("--hide", nargs="*", default=[], help="axis values not worth printing, e.g. clean")
a = ap.parse_args()

rows = [json.loads(l) for l in (Path(a.project) / "out/samples.jsonl").open(encoding="utf-8")]
chunks = (len(rows) + a.size - 1) // a.size
chunk = rows[a.chunk * a.size:(a.chunk + 1) * a.size]
print(f"# chunk {a.chunk} of {chunks} ({len(chunk)} rows) -> l4_raw/chunk_{a.chunk:03d}.txt")
hide = set(a.hide)
cur = None
for r in chunk:
    meta = {k: v for k, v in r.items() if k not in ("id", "variant", "axes")}
    path = meta.pop("path", None)
    names = (path or []) + list(meta.values()) if path is not None else list(meta.values())
    if names != cur:
        cur = names
        print("## " + " / ".join(map(str, names)))
    print(r["id"], "|", " / ".join(v for v in r["axes"].values() if v not in hide))
