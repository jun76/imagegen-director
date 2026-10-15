# IRIS 3B Turbo sequential image batch

> Reference implementation for one specific environment; see [../README.md](../README.md) for the contract a backend has to meet.

Loads the IRIS 3B base model, the merged Turbo LoRA and the Qwen3-VL-4B text encoder **once** in an existing IRIS Python environment, then generates images one by one from the `prompt_en` and `seed` of each JSONL row. Nothing is downloaded or installed.

This implementation is written for an NVIDIA GPU: it runs on `cuda` and stops if CUDA is not
available. Other devices would need code changes. The VRAM threshold and timings below refer to
the reference setup (RTX 5090) and are not requirements of IRIS itself.

## Setup

Copy `examples/backends/local_paths.example.json` to `~/.config/imagegen-director/local_paths.json`, or to `local_paths.json` in the directory you run the batch from, and fill in:

| key | meaning |
|---|---|
| `iris_python` | Python of an existing venv that can run IRIS (torch with CUDA, Pillow) |
| `iris_source` | IRIS checkout (the parent of `src/`) |
| `iris_models_dir` | model root containing `base/{config.yaml,model.safetensors}`, `turbo/r2-1000/student.safetensors`, `text_encoder/` (Qwen3-VL-4B-Instruct) |
| `unsloth_url` | optional; Unsloth server address for the GPU idle check (default `http://localhost:8888`) |
| `unsloth_api_key_file` | optional; text file containing only the Unsloth API key (`UNSLOTH_API_KEY` takes precedence) |
| `comfy_url` | optional; ComfyUI address checked for a busy queue |

Each value can also be given on the command line (`--runtime-python`, `--iris-source`, `--models-dir`, `--unsloth-url`, `--unsloth-api-key-file`, `--comfy-url`), which takes precedence. `IMAGEGEN_LOCAL_PATHS` points to a file elsewhere. Never commit this file: it holds machine-specific paths.

Models: base `speridlabs/iris-3b`, LoRA `pentacoxian-dev/iris-3b-turbo-lora` (r2-1000), text encoder `Qwen/Qwen3-VL-4B-Instruct`. Files are read offline and the batch stops if any is missing.

## Run

Run with any Python (`<skill>` is the installed skill, `<repo>` this repository, `<project>` the project folder); for generation the script re-launches itself in the IRIS venv.

```powershell
python <skill>/scripts/export_scenarios.py --project <project>
python <repo>/examples/backends/iris/batch.py --input <project>/out/scenarios.jsonl --output <project>/results/iris --dry-run
python <repo>/examples/backends/iris/batch.py --input <project>/out/scenarios.jsonl --output <project>/results/iris --limit 10
# continue all rows (completed ones are skipped)
python <repo>/examples/backends/iris/batch.py --input <project>/out/scenarios.jsonl --output <project>/results/iris
```

- `--limit` is the number of *pending* rows to generate in this run.
- `--dry-run` only validates the input; it imports neither torch nor IRIS and touches no GPU, network or output.
- Defaults: 1024x1024, 4 steps, shift 4, bf16, LoRA strength 1. Guidance is baked into the Turbo LoRA, so there is no extra CFG forward pass.

## Speed configuration

The masked-SDPA GQA heads are expanded with `repeat_interleave`, and only the LoRA-merged model is loaded via `load_model_streaming(..., lora_path, 1.0)`. There is no extra model copy, no live LoRA, no per-image reload, and no torch.compile. Reference timing (RTX 5090): about 1.3 s per image after a load of about 43 s.

## Sharing the GPU with other apps

This part reflects a machine that also runs Unsloth and ComfyUI; both checks are skipped when
those servers are not running. Before loading, the batch reads the Unsloth image / video / chat / training state and the ComfyUI queue, and stops (without interrupting anything) if something is busy or the state is unknown. A refused connection (Unsloth or ComfyUI) is treated as "not running", since a stopped server holds no GPU memory; timeouts and other errors stop the batch.

If an **idle** Unsloth image model is resident, it is released through the image unload API; no other model, process or service is stopped. The batch also stops if less than 16 GiB of VRAM is free before loading (a safety margin for this
setup; adjust it in `batch.py` for yours). The check cannot fully prevent another client from loading a model in between, so do not load other heavy models while it runs.

## Output, resume and recovery

- `images/<scenario_id>.png`, `records/<scenario_id>.json`, `runs/<run_id>.json`.
- A record stores the full input row, prompt, seed, settings, a fingerprint, timings and the SHA256. PNG and record are written to a temp file, fsynced and atomically replaced.
- Each PNG embeds an `iris_batch_record` text chunk with the input row and fingerprint, so a record lost in a crash can be rebuilt from the PNG without regenerating.
- On resume, completed images are decoded and checked against the fingerprint and hash, then skipped. `generating` / `failed` rows are regenerated.
- Corrupted or modified images and changed inputs/settings stop the batch instead of being overwritten. Use a new output directory after changing the input.
- `.batch.lock` is an OS file lock released when the process exits; a leftover file is harmless. Ctrl+C keeps all saved PNGs.

## Timing fields

- `generation_seconds`: CUDA-synchronized prompt encoding + 4-step generation + copy to CPU (PNG encoding excluded). The first image includes warm-up.
- `text_encode_seconds`: prompt encoding only.
- `load_seconds`: IRIS/torch import and model + encoder load.
- `total_worker_seconds` / `elapsed_seconds`: the whole worker run.

## Tests

```powershell
cd <repo>/examples/backends/iris; <iris-venv-python> -m unittest -v test_batch.py
```

The tests cover resume skipping, recovery when only the PNG was saved, input-change detection, dry-run with no network/GPU, locking, resuming after an unsaved generation failure, and not unloading a busy Unsloth model. Content quality and search relevance have to be evaluated separately.
