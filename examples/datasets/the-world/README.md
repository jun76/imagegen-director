# the-world: 10,000 general-purpose image-generation prompts

A prompt set for building a broad, general-purpose image collection that spreads over a wide
range of subjects (an attempt at 森羅万象, "all things in the universe"),
made with the [imagegen-director](../../../skills/imagegen-director/) skill and its `the-world`
preset. Intended for evaluating image search quality and usable for training.

## Contents

- `prompts/L4.jsonl` — 10,000 rows, one per image:
  ```json
  {"id": "03804", "l1": "4_life", "l2": "wild mammals", "l3": "lion", "variant": 4,
   "axes": {"media": "smartphone snapshot", "shot_scale": "medium view", ...},
   "prompt": "Casual handheld snapshot with ..., mid view from behind of a pride of lions ..."}
  ```
  - `l1`/`l2`/`l3`: position in the subject tree (10 / 108 / 1000 nodes)
  - `axes`: the sampled value of each axis, usable as ground-truth metadata (media type,
    viewpoint, count, lighting, weather, season, state, color, degradation, region, era)
  - `prompt`: flat English prompt, about 20-40 words, model-agnostic
- `report.md` — distribution of every axis against its target and the association between axes

## Properties

- Every leaf subject has 10 variants with 10 different media.
- Axis shares stay within 0.6 percentage points of their targets, except `count` (1.4 points
  fewer crowds, by design: creatures and body parts never get one). Cramér's V between axes is
  below 0.1 except the two pairs linked by exclusion rules (lighting x weather, media x color).
- No real people, brands, artists or named works. No quality incantations. No capture devices
  named in the prompts (they get drawn into the image). Creatures and body parts never appear
  as a mass.
- Images can be generated with any text-to-image model. They were generated end to end with
  IRIS 3B Turbo and Qwen-Image 2.1 Turbo during development; the images are not published here.

## Reproducing

```bash
cp -r skills/imagegen-director/presets/the-world my-world
python skills/imagegen-director/scripts/sampler.py --project my-world
```

reproduces every row's subject and axes exactly (same files and seed). The prompts themselves
were written by an LLM following `guides/prompt_writing.md` and are checked by
`scripts/assemble.py`; rewriting them gives different but rule-conforming wording.

## Generating the images

```bash
mkdir -p my-world/prompts && cp examples/datasets/the-world/prompts/L4.jsonl my-world/prompts/
python skills/imagegen-director/scripts/export_scenarios.py --project my-world
python examples/backends/iris/batch.py --input my-world/out/scenarios.jsonl --output my-world/results/iris
```

`out/scenarios.jsonl` carries `prompt_en` and `seed` per image for any text-to-image setup. The
IRIS batch above is one of two reference implementations for specific environments; see
[examples/backends](../../backends/) for the contract and the other one.

## License

[CC BY 4.0](../../../LICENSE-DATA.md). Suggested credit: "the-world prompt set from
imagegen-director, CC BY 4.0".
