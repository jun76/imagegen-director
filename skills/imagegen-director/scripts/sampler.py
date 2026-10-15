"""Sampler: give every leaf of the subject tree N axis combinations and write out/samples.jsonl.

- Values are drawn by quota-weighted random sampling: the further a value falls behind its
  target share, the more likely it is to be picked. This tracks the target distribution better
  than pure randomness and avoids the cross-axis correlation of a deterministic rotation.
- Within one leaf, a value is damped once it exceeds its expected count; axes marked
  unique_per_leaf never repeat within a leaf while unused values remain.
- exclusions in axes.yaml drop or narrow an axis based on values already chosen.
- subject_remaps replace values that must never appear for certain subjects. They are applied
  after the pick, so every other row keeps exactly the values it would get without them.
- Deterministic: the same project files and seed always give the same output.

usage: python scripts/sampler.py --project DIR [--per-leaf N] [--seed S]
"""

import argparse
import json
import math
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import project as projectlib  # noqa: E402


def apply_exclusions(axis, values, chosen, exclusions):
    """Drop this axis entirely (None) or narrow its candidates, given the values chosen so far."""
    values = dict(values)
    for rule in exclusions:
        if not all(chosen.get(a) == v for a, v in rule["if"].items()):
            continue
        if axis in rule.get("forbid", []):
            return None
        for v in rule.get("forbid_values", {}).get(axis, []):
            values.pop(v, None)
    return values or None


def pick(values, used, total_used, node_used, per_leaf, strict_unique, rng, beta):
    """Quota-weighted pick. Under-used values are favored, and repetition within a leaf is damped.

    Within a leaf, only values that exceed their expected count (rounded up) are suppressed.
    Forbidding all repeats would starve high-weight values and skew the overall distribution.
    """
    w_sum = sum(values.values())
    candidates = list(values)
    if strict_unique:
        fresh = [v for v in candidates if v not in node_used]
        candidates = fresh or candidates

    scores = []
    for v in candidates:
        p = values[v] / w_sum
        # Clamp the deficit: exclusion rules can make it pile up for some values
        deficit = max(-5.0, min(5.0, p * (total_used + 1) - used[v]))
        s = p * math.exp(beta * deficit)
        if node_used[v] >= math.ceil(p * per_leaf):
            s *= 0.05
        scores.append(s)
    return rng.choices(candidates, weights=scores)[0]


def sample(proj, per_leaf, seed, beta):
    rng = random.Random(seed)
    used = defaultdict(Counter)
    total_used = Counter()
    level_names = proj.config.get("level_names")
    width = projectlib.id_width(proj, len(proj.leaves) * per_leaf)
    rows = []
    for leaf in proj.leaves:
        node_used = defaultdict(Counter)
        for k in range(per_leaf):
            chosen = {}
            for axis, spec in proj.axes.items():
                if spec["applies_to"] is not None and not (spec["applies_to"] & (leaf.tags | set(leaf.path))):
                    continue
                values = apply_exclusions(axis, spec["values"], chosen, proj.exclusions)
                if values is None:
                    continue
                v = pick(values, used[axis], total_used[axis], node_used[axis], per_leaf,
                         strict_unique=spec["unique"], rng=rng, beta=beta)
                chosen[axis] = v
                used[axis][v] += 1
                total_used[axis] += 1
                node_used[axis][v] += 1
            for rule in proj.remaps:
                if proj.matches(leaf, rule["when"]):
                    for axis, mapping in rule["remap"].items():
                        if chosen.get(axis) in mapping:
                            chosen[axis] = mapping[chosen[axis]]
            chosen.update(proj.constants)
            row = {"id": f"{len(rows):0{width}d}"}
            if level_names and len(level_names) == len(leaf.path):
                row.update(zip(level_names, leaf.path))
            else:
                row.update(path=list(leaf.path[:-1]), subject=leaf.subject)
            row.update(variant=k, axes=chosen)
            rows.append(row)
    return rows


def cramers_v(rows, a, b):
    pairs = [(r["axes"][a], r["axes"][b]) for r in rows if a in r["axes"] and b in r["axes"]]
    if len(pairs) < 50:
        return None
    n = len(pairs)
    ca = Counter(x for x, _ in pairs)
    cb = Counter(y for _, y in pairs)
    cab = Counter(pairs)
    chi2 = 0.0
    for x in ca:
        for y in cb:
            e = ca[x] * cb[y] / n
            chi2 += (cab.get((x, y), 0) - e) ** 2 / e
    k = min(len(ca), len(cb)) - 1
    return math.sqrt(chi2 / (n * k)) if k > 0 else None


def leaf_of(row):
    return tuple(str(v) for k, v in row.items() if k not in ("id", "variant", "axes"))


def report(rows, proj):
    per_leaf = len(rows) // max(len(proj.leaves), 1)
    lines = ["# Sampling report\n", f"Total: {len(rows)} ({len(proj.leaves)} leaves)\n",
             f"**Images per leaf subject: {per_leaf}.** Each leaf is drawn {per_leaf} times with "
             "different axis values; ids are consecutive per leaf.\n"]
    if per_leaf > 3:
        lines.append(f"Check that every leaf can carry {per_leaf} images without looking repetitive "
                     "(a broad leaf, or a deliberate deep dive such as one character in many poses). "
                     "Otherwise add leaves and lower per_leaf.\n")
    if len(rows) < 500:
        lines.append("Small sample: shares below are noisy. Review the rows themselves "
                     "(scripts/show.py) rather than the statistics.\n")

    top = Counter(l.path[0] for l in proj.leaves)
    lines.append("## Leaves per top node\n")
    for name, c in top.items():
        lines.append(f"- {name}: {c}")

    lines.append("\n## Target vs. actual share per axis\n")
    lines.append("Max gap = largest difference between target and actual share (percentage points).\n")
    for axis, spec in proj.axes.items():
        cnt = Counter(r["axes"][axis] for r in rows if axis in r["axes"])
        n = sum(cnt.values())
        w_sum = sum(spec["values"].values())
        diffs = [(v, 100 * w / w_sum, 100 * cnt[v] / n if n else 0) for v, w in spec["values"].items()]
        worst = max(abs(t - a) for _, t, a in diffs)
        lines.append(f"### {axis}  (applied to {n}, max gap {worst:.1f}pt)\n")
        lines.append("| value | target % | actual % |\n|---|---:|---:|")
        for v, t, a in diffs:
            lines.append(f"| {v} | {t:.1f} | {a:.1f} |")
        lines.append("")

    if proj.constants:
        lines.append("## Constants (every row)\n")
        for k, v in proj.constants.items():
            lines.append(f"- {k}: {v}")
        lines.append("")

    lines.append("## Association between axes (Cramér's V)\n")
    lines.append("Closer to 0 means more independent. Pairs above 0.1 come from exclusion rules or indicate bias.\n")
    names = list(proj.axes)
    vs = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            v = cramers_v(rows, a, b)
            if v is not None:
                vs.append((v, a, b))
    vs.sort(reverse=True)
    lines.append("| axis A | axis B | V |\n|---|---|---:|")
    for v, a, b in vs[:10]:
        lines.append(f"| {a} | {b} | {v:.3f} |")

    uniq = [a for a, s in proj.axes.items() if s["unique"]]
    if uniq:
        lines.append("\n## Repeats within a leaf (unique_per_leaf axes)\n")
        by_leaf = defaultdict(list)
        for r in rows:
            by_leaf[leaf_of(r)].append(r)
        for a in uniq:
            dup = sum(1 for rs in by_leaf.values()
                      if len([r["axes"].get(a) for r in rs]) != len({r["axes"].get(a) for r in rs}))
            lines.append(f"- {a}: {dup} / {len(by_leaf)} leaves repeat a value")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--project", required=True, help="project directory; every file the script reads or writes is inside it")
    ap.add_argument("--per-leaf", type=int, help="override project.yaml per_leaf")
    ap.add_argument("--seed", type=int, help="override project.yaml seed")
    ap.add_argument("--beta", type=float, help="override project.yaml beta")
    args = ap.parse_args()

    proj = projectlib.load(args.project)
    cfg = proj.config
    if not args.per_leaf and "per_leaf" not in cfg:
        ap.error("set per_leaf (images per leaf subject) in project.yaml; agree on it with the user")
    per_leaf = args.per_leaf or int(cfg["per_leaf"])
    seed = args.seed if args.seed is not None else int(cfg.get("seed", 0))
    beta = args.beta if args.beta is not None else float(cfg.get("beta", 0.2))
    if not proj.axes:
        raise SystemExit("axes.yaml defines no axes")
    rows = sample(proj, per_leaf, seed, beta)

    out = proj.path("out/samples.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    rep = out.with_name("report.md")
    rep.write_text(report(rows, proj), encoding="utf-8")
    print(f"{len(rows)} rows ({len(proj.leaves)} leaves x {per_leaf}) -> {out}")
    print(f"report -> {rep}")


if __name__ == "__main__":
    main()
