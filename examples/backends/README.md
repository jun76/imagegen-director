# Example image backends

The skill writes prompts; generating the images is up to whatever text-to-image setup you
have. The two batch scripts here are **reference implementations for specific environments**,
used to generate the-world end to end during development. They are not general-purpose
clients: expect to adapt them, or to write a small batch for your own setup that follows the
contract below.

| backend | environment it assumes |
|---|---|
| [iris/](iris/) | an existing local IRIS 3B Turbo Python environment and model files; written for an NVIDIA GPU (CUDA) |
| [unsloth/](unsloth/) | a running Unsloth Studio server with Qwen-Image 2.1 Turbo, driven through its internal image API; the client itself needs no GPU |

Machine-specific paths go in `local_paths.json` (template:
[local_paths.example.json](local_paths.example.json)), looked up from `$IMAGEGEN_LOCAL_PATHS`,
then `./local_paths.json`, then `~/.config/imagegen-director/local_paths.json`. Never commit it.

## Backend contract

Anything that does the following works with the rest of the skill:

- **Input**: `<project>/out/scenarios.jsonl` from `scripts/export_scenarios.py`. Each row is the L4 row
  plus `scenario_id`, `prompt_en` and an integer `seed`. Send `prompt_en` unchanged; the prompts
  are model-agnostic and already rule-checked.
- **Output**: `<output>/images/<scenario_id>.png`, with `<output>` inside the project folder
  (`<project>/results/<backend>`), ideally with a per-image record
  `<output>/records/<scenario_id>.json` holding at least `"scenario"` (the full input row) plus
  the settings used.
- **Reproducible**: the same row and seed with the same settings gives the same image.
- **Resumable**: rerunning the same command skips finished images, so a long run can be stopped
  and continued.
- **Prompt changes**: after prompts are rewritten, `scripts/prune_results.py` moves images made
  from old prompts to `<output>_superseded/` (it compares each record's `scenario` with the
  current row), so the next run regenerates only changed rows. Without records, move the
  affected images aside yourself.
- Image size comes from `project.yaml` `image` and is passed as `--size WxH` in the examples.
