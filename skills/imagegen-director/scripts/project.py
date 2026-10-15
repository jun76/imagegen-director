"""Load an imagegen-director project directory (project.yaml, taxonomy.yaml, axes.yaml, rules.yaml).

Shared by the other scripts. Schema: guides/schema.md.
"""
from dataclasses import dataclass, field
from pathlib import Path

import yaml

SKILL = Path(__file__).resolve().parent.parent
META_PREFIX = "_"


@dataclass
class Leaf:
    path: tuple            # names from the top node down to the leaf (the leaf is last)
    tags: frozenset        # tags of every ancestor node

    @property
    def subject(self):
        return self.path[-1]


@dataclass
class Project:
    root: Path
    config: dict
    leaves: list
    groups: dict
    axes: dict = field(default_factory=dict)
    exclusions: list = field(default_factory=list)
    remaps: list = field(default_factory=list)
    constants: dict = field(default_factory=dict)

    def path(self, name):
        return self.root / name

    def matches(self, leaf, cond):
        """True if a `when`/`unless` condition matches the leaf.

        cond keys (any one matching is enough):
          group: name or list of names from taxonomy.yaml groups
          nodes: node names anywhere on the leaf's path (including the leaf)
          tags:  tags of the leaf's ancestors
        """
        if not cond:
            return True
        names = set(leaf.path)
        groups = cond.get("group", [])
        for g in [groups] if isinstance(groups, str) else groups:
            if g not in self.groups:
                raise ValueError(f"unknown group '{g}' (define it in taxonomy.yaml groups)")
            if names & self.groups[g]:
                return True
        if names & set(cond.get("nodes", [])):
            return True
        return bool(leaf.tags & set(cond.get("tags", [])))


def _walk(node, path, tags, out):
    if isinstance(node, list):
        for name in node:
            out.append(Leaf(tuple(path) + (str(name),), frozenset(tags)))
        return
    if not isinstance(node, dict):
        raise ValueError(f"node {'/'.join(path)} must be a mapping or a list of leaves")
    own = set(node.get("_tags", []))
    for name, child in node.items():
        if not str(name).startswith(META_PREFIX):
            _walk(child, path + [str(name)], tags | own, out)


def load(root):
    root = Path(root).resolve()
    if not (root / "project.yaml").is_file():
        raise SystemExit(f"ERROR: {root} is not a project directory (no project.yaml)")
    config = yaml.safe_load((root / "project.yaml").read_text(encoding="utf-8")) or {}
    tax = yaml.safe_load((root / config.get("taxonomy", "taxonomy.yaml")).read_text(encoding="utf-8"))
    leaves = []
    _walk(tax["tree"], [], set(), leaves)
    subjects = [l.subject for l in leaves]
    dup = {s for s in subjects if subjects.count(s) > 1}
    if dup:
        raise ValueError(f"leaf subjects must be unique; duplicated: {sorted(dup)[:5]}")
    groups = {g: set(map(str, names)) for g, names in (tax.get("groups") or {}).items()}
    known = {n for l in leaves for n in l.path}
    for g, names in groups.items():
        unknown = names - known
        if unknown:
            raise ValueError(f"group '{g}' names unknown nodes: {sorted(unknown)[:5]}")
    project = Project(root, config, leaves, groups)

    axes_file = root / config.get("axes", "axes.yaml")
    if axes_file.exists():
        raw = yaml.safe_load(axes_file.read_text(encoding="utf-8")) or {}
        project.exclusions = raw.pop("exclusions", []) or []
        project.remaps = raw.pop("subject_remaps", []) or []
        project.constants = raw.pop("constants", {}) or {}
        all_tags = {t for l in leaves for t in l.tags}
        for name, spec in raw.items():
            applies = spec.get("applies_to")
            if applies:
                unknown = set(applies) - all_tags - known
                if unknown:
                    raise ValueError(f"axis '{name}' applies_to unknown tags/nodes: {sorted(unknown)}")
            project.axes[name] = {
                "values": {str(k): float(v) for k, v in spec["values"].items()},
                "applies_to": set(applies) if applies else None,
                "unique": bool(spec.get("unique_per_leaf", False)),
            }
    return project


def load_rules(project):
    """Universal rules merged with the project's rules.yaml (overrides applied)."""
    universal = yaml.safe_load((SKILL / "library/rules/universal.yaml").read_text(encoding="utf-8"))["rules"]
    rules_file = project.root / project.config.get("rules", "rules.yaml")
    own = yaml.safe_load(rules_file.read_text(encoding="utf-8")) if rules_file.exists() else {}
    own = own or {}
    overrides = own.get("overrides") or {}
    merged = []
    for rule in universal:
        o = overrides.get(rule["id"], {})
        if o.get("disabled"):
            continue
        merged.append({**rule, **{k: v for k, v in o.items() if k != "disabled"}})
    unknown = set(overrides) - {r["id"] for r in universal}
    if unknown:
        raise ValueError(f"rules.yaml overrides unknown universal rules: {sorted(unknown)}")
    return merged + list(own.get("rules") or [])


def id_width(project, total):
    return int(project.config.get("id_width") or max(4, len(str(max(total - 1, 0)))))
