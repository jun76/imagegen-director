# Preset: the-world

A broad, general-purpose image set spread over a wide range of subjects, built for evaluating
image search quality. 1000 subjects cannot cover the world; the aim is breadth and balance,
not completeness.

- 10 top categories (abstract concepts, cosmos, matter, earth, life, human body and mind, human
  activities, artifacts, symbols, imagined worlds), 108 middle categories, 1000 leaf subjects.
- 13 axes: media, shot scale, angle, composition, count, lighting, weather, season, state, color,
  quality, region, era. 10 variants per leaf -> 10,000 prompts.
- Sampling is deterministic: `scripts/sampler.py` on these files reproduces the published
  samples byte for byte.

The 10,000 written prompts are published outside the skill, in the repository's
`examples/datasets/the-world/`. This preset holds only what is needed to reproduce or extend them.

Start a project from it by copying this folder; then change `project.yaml` (`name`,
`per_leaf`), prune or extend `taxonomy.yaml`, and adjust `axes.yaml`.
