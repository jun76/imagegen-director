# imagegen-director

English | [日本語](README.ja.md)

<p align="center">
<a href="media/L4-00508.png"><img src="media/thumbs/L4-00508.jpg" width="24%" alt="great red spot of Jupiter (child's drawing)"></a>
<a href="media/L4-01860.png"><img src="media/thumbs/L4-01860.jpg" width="24%" alt="mossy old-growth forest (low-poly toy 3D render)"></a>
<a href="media/L4-03798.png"><img src="media/thumbs/L4-03798.jpg" width="24%" alt="ostrich (photorealistic 3D render)"></a>
<a href="media/L4-05916.png"><img src="media/thumbs/L4-05916.jpg" width="24%" alt="elders playing Go (ink wash painting)"></a><br>
<a href="media/L4-06514.png"><img src="media/thumbs/L4-06514.jpg" width="24%" alt="ramen (anime cel illustration)"></a>
<a href="media/L4-06820.png"><img src="media/thumbs/L4-06820.jpg" width="24%" alt="umbrella (infrared thermal or X-ray image)"></a>
<a href="media/L4-06943.png"><img src="media/thumbs/L4-06943.jpg" width="24%" alt="necklace (screenshot)"></a>
<a href="media/L4-07208.png"><img src="media/thumbs/L4-07208.jpg" width="24%" alt="bicycle (encyclopedia or textbook illustration)"></a><br>
<a href="media/L4-07570.png"><img src="media/thumbs/L4-07570.jpg" width="24%" alt="study (oil painting)"></a>
<a href="media/L4-08561.png"><img src="media/thumbs/L4-08561.jpg" width="24%" alt="emoji (professional photo)"></a>
<a href="media/L4-09248.png"><img src="media/thumbs/L4-09248.jpg" width="24%" alt="phoenix (photorealistic 3D render)"></a>
<a href="media/L4-09392.png"><img src="media/thumbs/L4-09392.jpg" width="24%" alt="dwarf (oil painting)"></a><br>
<a href="media/L4-09619.png"><img src="media/thumbs/L4-09619.jpg" width="24%" alt="floating rock mountains (pixel art)"></a>
<a href="media/L4-09757.png"><img src="media/thumbs/L4-09757.jpg" width="24%" alt="room floating in the sky (photorealistic 3D render)"></a>
<a href="media/L4-09787.png"><img src="media/thumbs/L4-09787.jpg" width="24%" alt="landscape with a giant eye (pen and ink line drawing)"></a>
<a href="media/L4-09979.png"><img src="media/thumbs/L4-09979.jpg" width="24%" alt="city with flying cars (clay diorama or miniature)"></a>
</p>

<p align="center"><sub>16 of the 10,000 images from the <a href="examples/datasets/the-world/">the-world</a> example
(Qwen-Image 2.1 Turbo, 1024x1024). Click an image for full size. The images are not covered by
this repository's licenses, see <a href="media/NOTICE.md">media/NOTICE.md</a>.</sub></p>

An agent skill that directs the creation of large, varied, on-theme sets of image-generation
prompts, and optionally the images themselves.

Ask for "100 anime-style character images", "1000 map tiles for my game", or "an image set
over a wide range of subjects", and the skill interviews you, builds a subject tree and a set of
orthogonal axes, samples them evenly, and writes out model-agnostic prompts that pass
machine-checked rules.

## How it works

1. **Purpose and scale.** What the images are for, how many, and how many images each subject
   gets: few per subject for a broad collection, many for a deliberate deep dive.
2. **Subject tree** (`taxonomy.yaml`). What to depict, expanded level by level with you. The
   leaves are the subjects.
3. **Axes** (`axes.yaml`). How the images vary: medium, framing, light, weather, expression,
   pose, ... with weights, plus constants that every image shares.
4. **Rules** (`rules.yaml`). Machine-checked constraints on the prompts, on top of universal
   rules for common failure modes (no capture devices drawn into the picture, no dense masses of
   creatures, no quality incantations).
5. **Sampling.** Every subject gets its combinations by quota-weighted sampling: evenly
   spread, independent across axes, deterministic.
6. **Prompts.** The agent writes one flat English prompt per row; the rules gate the result.
7. **Images** (optional). Export a JSONL of prompts and seeds for any text-to-image setup,
   test a few dozen, turn every problem into a rule, then run the rest.

Every step ends with a file in one project folder, so a session can stop and resume, and the
prompts can be regenerated without losing the fixes.

## Repository

```
skills/imagegen-director/      the skill
  SKILL.md                     workflow the agent follows
  guides/                      file schema, prompt-writing rules, known pitfalls
  library/axes/                reusable axes (media, angle, lighting, expression, pose, outfit, ...)
  library/rules/universal.yaml rules every prompt must pass
  scripts/                     sampler, assemble (rule checks), export, show, prune
  presets/the-world/           1000 subjects x 13 axes, the setup behind examples/datasets/the-world
examples/
  datasets/the-world/          10,000 published prompts made with the preset
  backends/                    reference image batches for two specific local setups, and the backend contract
media/                         sample images for this README
```

## Install

Copy `skills/imagegen-director/` into your agent's skills directory, e.g. for Claude Code:

```bash
cp -r skills/imagegen-director ~/.claude/skills/
```

Then ask your agent for an image set, e.g. "I want 300 varied images of street food for a
search test".

Requirements: Python 3.10+ with PyYAML for the scripts; the skill itself needs no GPU. Image
generation is not bundled:
use any text-to-image setup that meets the small contract in
[examples/backends](examples/backends/), or adapt one of the two reference batches there.

## Quick start (manual)

```bash
cp -r skills/imagegen-director/presets/the-world my-set     # or let the skill create a project
python skills/imagegen-director/scripts/sampler.py --project my-set
python skills/imagegen-director/scripts/show.py --project my-set --chunk 0
# write prompts into my-set/l4_raw/chunk_000.txt ..., then
python skills/imagegen-director/scripts/assemble.py --project my-set
```

## Example dataset

[examples/datasets/the-world](examples/datasets/the-world/): 10,000 prompts over 1000
subjects, from abstract concepts to imagined worlds, each with its sampled axes as metadata.
It was made with the `the-world` preset at 10 images per subject; for a broad set, fewer
images per subject and more subjects may give better results.

## License

- Code and the skill (`skills/`, `examples/backends/`): [MIT](LICENSE)
- Prompt datasets (`examples/datasets/`): [CC BY 4.0](LICENSE-DATA.md)
- Sample images (`media/`): no license granted; generated with Qwen-Image-2.1-Turbo under the
  Qwen Research License (non-commercial). See [media/NOTICE.md](media/NOTICE.md).
