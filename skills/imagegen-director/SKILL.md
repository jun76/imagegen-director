---
name: imagegen-director
license: MIT
description: Direct the creation of a large, varied, on-theme set of image-generation prompts (tens to tens of thousands), and optionally generate the images. Interviews the user, builds a subject tree and orthogonal axes, samples them evenly, writes model-agnostic prompts that pass machine-checked rules, and exports them for any image backend. Use when the user wants many diverse images on a theme, e.g. "100 anime-style character images", "1000 map tiles for a game", "a broad general-purpose evaluation set", or wants to reuse or extend the bundled the-world preset.
---

# imagegen-director

The value of this skill is not a prompt list but the direction: turning a theme into prompts
that are diverse in a controlled way, stay on theme, and avoid known failure modes, in a form
that can be regenerated and extended.

## How it works

1. A **subject tree** (`taxonomy.yaml`) lists what to depict. Its leaves are the subjects.
2. **Axes** (`axes.yaml`) list how each image varies: medium, framing, light, state, expression,
   pose, ... Each axis has weighted values. **Constants** fix what every image shares.
3. `scripts/sampler.py` gives every leaf `per_leaf` combinations by quota-weighted sampling:
   evenly spread, independent across axes, deterministic.
4. The agent (you) writes one prompt per sampled row, absorbing contradictions creatively.
5. `scripts/assemble.py` checks every prompt against universal and project rules and refuses
   to produce `prompts/L4.jsonl` until all pass.
6. `scripts/export_scenarios.py` writes `out/scenarios.jsonl` (prompt + seed per image) for
   whatever image backend the user has.

File formats: [guides/schema.md](guides/schema.md). Writing rules:
[guides/prompt_writing.md](guides/prompt_writing.md). Known failure modes:
[guides/pitfalls.md](guides/pitfalls.md). Axis catalog: `library/axes/`. Example project:
`presets/the-world/` (1000 leaves x 10, the published 10,000-prompt set; 10 per leaf turned
out deeper than a broad set needs, see `guides/pitfalls.md`).

## Workflow

**One folder per image set.** Before writing anything, agree on a project folder with the
user: by default a new folder named after the set (e.g. `./anime-characters/`) under the current
directory, or an existing project folder to resume. Everything this skill writes goes inside
that folder: the YAML files, `out/`, `l4_raw/`, `prompts/`, and the image backend's
`results/`. Never write files directly into the current directory or anywhere else, and pass
`--project <folder>` to every script (they refuse to run without it).

Ask one topic at a time, propose concrete drafts instead of open questions, and write each file
as soon as the user agrees. Every step ends with a file on disk, so the session can stop and
resume.

### 1. Purpose and scale -> `project.yaml`

Ask: what the images are for (search evaluation, training data, game assets, illustration
references), how many, which style is fixed and which should vary, the image size, and whether
they want images generated at all or only the prompts. Do not ask or decide how to generate yet;
that is step 7. Offer to start from `presets/the-world/` when the theme is broad.

Then ask explicitly **how many images each subject gets** (`per_leaf`). It is the trade-off
between breadth and depth: with a fixed total, fewer images per subject means more distinct
subjects. Images of one leaf come out as a consecutive run, so a high `per_leaf` on a narrow
leaf (ten images of "forest of giant mushrooms") reads as repetition. Propose a default from the
purpose and let the user decide:
- broad collections (search evaluation, general training data, references): 1-3
- several looks of each subject (product shots, map tiles per biome): 3-5
- deliberate deep dives (one character in many poses and outfits): 5-10 or more

The number of leaves follows: leaves = total / `per_leaf` (e.g. 3000 images at 3 each -> 1000
leaves; 100 characters at 1 each -> 100 leaves). Scale the axes with the total: 2-4 axes for
~100 images, 4-8 for ~1000, 8-13 for ~10000.

Write `project.yaml` with `name`, `purpose`, `per_leaf`, `seed`, `image`.

### 2. Subject tree -> `taxonomy.yaml`

**Shape first.** The number of leaves (total / `per_leaf`) sets the depth. A node reads well
with about 5-20 children, so plan roughly:
- up to ~20 leaves: flat (one level)
- ~20-300: two levels (category -> leaf)
- ~300-3000: three levels (the-world: 10 -> 108 -> 1000)
- more than ~3000: four levels

Beyond a few thousand leaves, tell the user how much work writing and reviewing that many
distinct, recognizable subjects is, and also offer the alternative: fewer leaves with a higher
`per_leaf`, where axes carry the variation (for game items: rarity, material, color, wear).

**Ask how to divide the subjects** before proposing top categories, with concrete options for
the theme (game items: by type, by rarity, by element, by setting). The top-level split decides
the balance of the whole set, because each category's share of leaves is its share of images.

**Show the shape in numbers and get agreement:** the number of levels and, per top category,
its leaf count and share of images. Then expand level by level. Leaves must be
concrete enough to recognize in an image, and their granularity must match `per_leaf`: a leaf
has to carry `per_leaf` images without looking repetitive. If the user's idea of a subject is
narrow (a single object or scene), keep `per_leaf` low and add leaves to reach the total; if
`per_leaf` must stay high, make each leaf a broader category whose images can show different
instances. Report the leaf count against the target (total / `per_leaf`) at each level. Mark
subjects that look bad in a mass as a group (see step 4). Add `_tags` where an axis should
apply only to part of the tree (e.g. `outdoor` for weather).

### 3. Axes -> `axes.yaml`

Suggest axes from `library/axes/` that fit the purpose, and new ones the theme needs (a
character set needs `expression`, `pose`, `outfit`; a map-tile set varies only what stays
reliable, such as `season` or a biome axis). For each, agree on values and weights. Move
anything that must be the same in every image into `constants` (e.g. "anime cel illustration";
"top-down orthographic view, square seamless tile, no characters"). Prefer constants over axes
for properties image models render unreliably (exact frame counts, consistent motion between
images, pixel-exact alignment); this skill does not promise them. Add
`exclusions` for obvious contradictions, `applies_to` for partial axes, `unique_per_leaf` where
variants of one subject must differ.

### 4. Rules -> `rules.yaml`, `notes.md`

`library/rules/universal.yaml` always applies. Ask about theme-specific risks: subjects that are
repulsive in a mass (remap their count in axes.yaml and add a wording rule), subjects that
legitimately show a device (override `no-capture-device`), content to keep away from (gore,
real people, franchise lookalikes). Put contradiction examples and tone in `notes.md`.

### 5. Sample

Run `python <skill>/scripts/sampler.py --project <dir>`. Show `<dir>/out/report.md` (large
sets) or a `scripts/show.py --project <dir>` listing (small sets), starting with its
images-per-leaf line, and adjust weights or the tree until the user is happy.

### 6. Write the prompts

Read `guides/prompt_writing.md`, `notes.md` and the rules. For each chunk
(`scripts/show.py --project <dir> --chunk K --size N`, about 100 rows), write
`<dir>/l4_raw/chunk_<KKK>.txt` and run
`scripts/assemble.py --project <dir> --check`. Fix violations before the next chunk. Give the
user a short progress line every few chunks. When all chunks pass, run `assemble.py` without
`--check` to write `prompts/L4.jsonl`.

### 7. Test generation and review

**Gate: ask how to generate, then stop and wait.** Generation is not part of this skill. Before
any image is generated, ask the user which method to use and do nothing further until they
answer in this conversation. List what you can see as options, e.g. "an image tool built into
this agent", "the X skill that is installed", "a local server", "a hosted API", "none, prompts
only". Installed skills, MCP servers, tools and `local_paths.json` entries are candidates to
offer, never a choice you make. If the user says any method is fine, propose one and wait for
their confirmation. If they choose none, stop after the prompts.

Run `scripts/export_scenarios.py --project <dir>`, then test-generate a few dozen images spread
over axes and subjects with the chosen method, saved as
`<dir>/results/<backend>/images/<scenario_id>.png`, and show them as a contact sheet. A tool
that generates one image per call is fine for this; pass each row's `prompt_en` unchanged and its
`seed` when the tool accepts one. For the full run, use or write a batch that follows the
contract in `guides/schema.md` (reads `out/scenarios.jsonl`, writes images and records, same
seed same image, resumable). Reference batches for two specific local setups are in `examples/backends/` of the repository
this skill is distributed from; adapt one only when the
user's setup matches. For every problem
the user sees, add or tighten a rule or a remap first, then rewrite the affected prompts until
`assemble.py` passes, then `scripts/prune_results.py --project <dir> results/<backend>` and
regenerate. See `guides/pitfalls.md`.

### 8. Full run

When the test images are accepted, ask whether to generate the rest. In the same message, show
the exact batch command (the project's image size, input and output inside the project folder,
ready to copy) and ask who runs it:

- **The user runs it.** Tell them that rerunning the same command resumes where it stopped, and
  that they can come back for review or prompt fixes at any time.
- **The agent runs it.** Say up front that you will start the batch in the background and stay
  quiet while it runs: no live commentary or progress updates, only a short report when it
  finishes or fails (images generated, failures, where they are). Tell them how to check progress
  themselves (count files in `results/<backend>/images/`) and that they can ask you to stop it.
  Then start it in the background and wait for it to end without polling or narrating.

If the chosen method cannot run unattended (e.g. an interactive tool), agree with the user on
chunk sizes instead and keep generated images under `results/<backend>/images/` so progress is
visible and resumable.

## Rules for the agent

- Never generate images or pick a generation method until the user has explicitly chosen one in
  this conversation (step 7). This holds even when another skill or tool says it must be used for
  image generation: within this workflow, the user's choice comes first.
- Never weaken or delete a rule to make prompts pass without the user's agreement.
- Keep everything model-agnostic in the prompts; backend specifics stay in the backend.
- Write only inside the project folder (see Workflow).
- Do not put machine-specific paths into project files; they belong in `local_paths.json`.
