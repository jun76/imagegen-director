# Project file schema

A project is one directory, and everything belonging to an image set lives in it. The skill
writes these files while interviewing the user; the scripts take it as `--project <dir>` and
never write outside it. All files are YAML except the generated JSONL and Markdown.

```
<project>/
  project.yaml        what and how many
  taxonomy.yaml       subject tree (+ groups)
  axes.yaml           axes to vary, constants, exclusions, subject remaps
  rules.yaml          project-specific prompt rules (on top of library/rules/universal.yaml)
  notes.md            free-form writing notes for this theme (contradiction examples, tone)
  out/samples.jsonl   scripts/sampler.py
  out/report.md       scripts/sampler.py
  l4_raw/*.txt        prompts written by the agent, "<id> <prompt>" per line
  prompts/L4.jsonl    scripts/assemble.py (only when every rule passes)
  out/scenarios.jsonl scripts/export_scenarios.py, input of the image backends
  results/<backend>/  images, written by whatever generates them (see "Image backends")
```

## project.yaml

| key | default | meaning |
|---|---|---|
| `name` | required | short identifier, also the default scenario prefix |
| `purpose` | | one paragraph: what the images are for. The writer reads it. |
| `per_leaf` | required | images per leaf subject (breadth vs depth). Total prompts = leaves x per_leaf. Agree on it with the user; 1-3 for broad sets. |
| `seed` | 0 | sampler seed. Same files + seed = same samples. |
| `beta` | 0.2 | quota sensitivity. Higher tracks target shares more strictly, but too high (~1) creates cross-axis correlation. |
| `level_names` | | e.g. `[l1, l2, l3]`: write the leaf path as these fields when the depth matches. Otherwise rows carry `path` and `subject`. |
| `id_width` | auto | digits of row ids (auto: at least 4) |
| `scenario_prefix` | `<name>-` | prefix of scenario ids and image file names |
| `seed_base` | 0 | image seed = seed_base + numeric id |
| `image` | | `{width, height}` passed to the backends as `--size WxH` |

## taxonomy.yaml

```yaml
groups:                     # optional; named sets of node names, used by axes.yaml and rules.yaml
  mass-sensitive: [insects and spiders, body parts, lotus]
tree:
  animals:                  # a node is a mapping ...
    _tags: [outdoor]        # optional tags, inherited by every leaf below
    _weight: 20             # optional planning note (share of leaves); ignored by the sampler
    insects and spiders: [honeybee, ladybug, dragonfly]   # ... or a list of leaf subjects
  household objects: [kettle, chair, lamp]
```

- Any depth. Leaves are the strings in lists; they must be unique across the tree.
- A small project can be flat: `tree: {subjects: [knight, mage, archer]}`.
- Node names starting with `_` are metadata.

## axes.yaml

```yaml
constants:                  # added unchanged to every row
  media: anime cel illustration
  background: plain flat background

expression:                 # an axis: values with relative weights
  values: {neutral: 3, gentle smile: 3, surprised: 1}
weather:
  applies_to: [outdoor]     # tags or node names; omit to apply everywhere
  values: {clear: 3, rain: 1}
media:
  unique_per_leaf: true     # variants of one leaf never share a value while others remain
  values: {...}

exclusions:                 # drop or narrow an axis given values chosen earlier (axes are sampled in file order)
  - {if: {media: product photo on white background}, forbid: [weather]}
  - {if: {lighting: sunny daylight}, forbid_values: {weather: [rain, snow]}}

subject_remaps:             # values that must never appear for some subjects; applied after the pick,
  - when: {group: mass-sensitive}          # so no other row changes
    remap: {count: {crowd or many: a few}}
```

Copy axes from `library/axes/` and adapt them. Unknown keys such as `description` and `notes`
are ignored by the sampler, so library files can be pasted as they are.

## rules.yaml

```yaml
overrides:                  # narrow or disable a universal rule
  no-capture-device: {unless: {group: device-subjects}}
  no-dense-mass: {disabled: true}
rules:
  - id: mass-sensitive-wording
    description: why the rule exists (the writer reads it)
    when: {group: mass-sensitive}       # optional; group / nodes / tags
    unless: {nodes: [ant colony]}       # optional
    forbid: '\b(many|swarm)\b'          # violated if the regex matches the prompt
    require: '\b(a few|single)\b'       # violated if the regex does not match
    deny_axes: {count: [crowd or many]} # violated if the row was sampled with these values
```

Conditions match a leaf when any listed group contains a node on its path, any listed node is
on its path, or any listed tag is among its inherited tags. Regexes are case-insensitive.

## Row formats

`out/samples.jsonl`: `{"id", <level fields> | "path" + "subject", "variant", "axes": {...}}`

`prompts/L4.jsonl`: the sample row plus `"prompt"`.

`out/scenarios.jsonl`: the L4 row plus `"scenario_id"`, `"prompt_en"`, `"seed"`.

## Image backends

Any text-to-image setup works if its batch:
- reads `out/scenarios.jsonl` and sends `prompt_en` unchanged with the integer `seed`;
- writes `results/<backend>/images/<scenario_id>.png`, and preferably
  `results/<backend>/records/<scenario_id>.json` with `"scenario"` (the full input row) and the
  settings used, which lets `scripts/prune_results.py` move images of changed prompts aside;
- gives the same image for the same row, seed and settings;
- skips finished images when rerun, so long runs can stop and resume.

Reference batches for two specific local setups are in `examples/backends/` of the repository
this skill is distributed from.
