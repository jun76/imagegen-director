"""Convert prompts/L4.jsonl into out/scenarios.jsonl, the input of the image backends.

Each row keeps every L4 field and adds:
  scenario_id: <scenario_prefix><id>   (project.yaml scenario_prefix, default "<name>-")
  prompt_en:   the prompt
  seed:        seed_base + numeric id, so rerunning gives the same image for the same id

usage: python scripts/export_scenarios.py --project DIR [--seed-base N]
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import project as projectlib  # noqa: E402

ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
ap.add_argument("--project", required=True, help="project directory; every file the script reads or writes is inside it")
ap.add_argument("--seed-base", type=int, help="override project.yaml seed_base (default 0)")
a = ap.parse_args()

proj = projectlib.load(a.project)
prefix = proj.config.get("scenario_prefix", f"{proj.config.get('name', 'img')}-")
base = a.seed_base if a.seed_base is not None else int(proj.config.get("seed_base", 0))
out = proj.path("out/scenarios.jsonl")
n = 0
with out.open("w", encoding="utf-8") as fo:
    for line in proj.path("prompts/L4.jsonl").open(encoding="utf-8"):
        r = json.loads(line)
        fo.write(json.dumps({"scenario_id": prefix + r["id"], "prompt_en": r["prompt"],
                             "seed": base + int(r["id"]), **r}, ensure_ascii=False) + "\n")
        n += 1
print(f"{n} rows -> {out}")
