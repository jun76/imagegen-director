"""Check the written prompts against the rules and merge them into prompts/L4.jsonl.

Prompts are written into <project>/l4_raw/*.txt, one per line: "<id> <prompt>".
Every prompt is checked against library/rules/universal.yaml plus the project's rules.yaml.
prompts/L4.jsonl is written only when all rows are present and no rule is violated, so a
regenerated L4 cannot silently bring back a problem that was fixed before. Exit code 1 otherwise.

usage: python scripts/assemble.py --project DIR [--check]
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import project as projectlib  # noqa: E402


def compile_rules(rules):
    out = []
    for r in rules:
        c = dict(r)
        for key in ("forbid", "require"):
            if r.get(key):
                c[key] = re.compile(r[key], re.IGNORECASE)
        out.append(c)
    return out


def subject_of(row):
    return row.get("subject") or [v for k, v in row.items() if k not in ("id", "variant", "axes")][-1]


def violations(proj, leaf, row, text, rules):
    """Human-readable violations of one prompt. A rule applies when `when` matches and `unless`
    does not; it is violated by a `forbid` match, a missing `require` match, or a sampled value
    listed in `deny_axes`."""
    out = []
    for r in rules:
        if "when" in r and not proj.matches(leaf, r["when"]):
            continue
        if "unless" in r and proj.matches(leaf, r["unless"]):
            continue
        if r.get("forbid") and (m := r["forbid"].search(text)):
            out.append(f"{r['id']}: '{m.group(0)}'")
        if r.get("require") and not r["require"].search(text):
            out.append(f"{r['id']}: required wording missing")
        for axis, bad in (r.get("deny_axes") or {}).items():
            if row["axes"].get(axis) in bad:
                out.append(f"{r['id']}: sampled {axis} '{row['axes'][axis]}'")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--project", required=True, help="project directory; every file the script reads or writes is inside it")
    ap.add_argument("--check", action="store_true", help="report only; do not write prompts/L4.jsonl")
    a = ap.parse_args()

    proj = projectlib.load(a.project)
    rules = compile_rules(projectlib.load_rules(proj))
    leaves = {l.subject: l for l in proj.leaves}
    rows = {}
    for line in proj.path("out/samples.jsonl").open(encoding="utf-8"):
        r = json.loads(line)
        rows[r["id"]] = r

    prompts, problems = {}, []
    for f in sorted(proj.path("l4_raw").glob("*.txt")):
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            m = re.match(r"^(\S+)\s+(.+)$", line.strip())
            pid, text = (m.group(1), m.group(2).strip()) if m else (None, None)
            if pid not in rows:
                problems.append(f"{f.name}:{n}: unknown id or malformed line")
                continue
            if pid in prompts:
                problems.append(f"{f.name}:{n}: duplicate id {pid}")
            prompts[pid] = text
            row = rows[pid]
            subject = subject_of(row)
            problems += [f"{pid} ({subject}): {v}"
                         for v in violations(proj, leaves[subject], row, text, rules)]

    missing = [i for i in rows if i not in prompts]
    words = [len(t.split()) for t in prompts.values()]
    print(f"prompts: {len(prompts)} / {len(rows)}  missing: {len(missing)}")
    if missing:
        print("first missing:", missing[:5])
    if words:
        print(f"words: min {min(words)} / mean {sum(words) / len(words):.1f} / max {max(words)}")
    print(f"rule violations: {len(problems)}")
    for p in problems[:50]:
        print("  " + p)
    if len(problems) > 50:
        print(f"  ... and {len(problems) - 50} more")

    if problems or missing:
        print("prompts/L4.jsonl NOT written", file=sys.stderr)
        return 1
    if a.check:
        return 0
    out = proj.path("prompts/L4.jsonl")
    out.parent.mkdir(exist_ok=True)
    with out.open("w", encoding="utf-8") as fo:
        for i, r in rows.items():
            fo.write(json.dumps({**r, "prompt": prompts[i]}, ensure_ascii=False) + "\n")
    print("->", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
