# Unsloth Qwen-Image 2.1 Turbo batch client

> Reference implementation for one specific environment; see [../README.md](../README.md) for the contract a backend has to meet.

Python 3.10+, standard library only; the client needs no GPU (the Unsloth server does the
generation). Sends the `prompt_en` and integer `seed` of each JSONL row unchanged to the Unsloth synchronous image API, one request per image (steps 8, CFG 1). No prompt rewriting or LLM is involved. If no image model is loaded, the official Turbo configuration is loaded automatically. Unsloth itself is never started, interrupted or explicitly unloaded.

## Setup

Copy `examples/backends/local_paths.example.json` to `~/.config/imagegen-director/local_paths.json`, or to `local_paths.json` in the directory you run the batch from, and fill in:

| key | meaning |
|---|---|
| `unsloth_url` | optional; server address (default `http://localhost:8888`) |
| `unsloth_api_key_file` | optional; path of a text file that contains only the Unsloth API key |
| `unsloth_turbo_dir` | **server-side** directory of `qwen-image-2.1-turbo-Q8_0.gguf` and `qwen_image_2.1_vae_bf16.safetensors` |
| `unsloth_models_dir` | **server-side** models root containing `text_encoders/qwen3vl_8b_int8_convrot.safetensors` |

Command-line flags (`--url`, `--api-key-file`, `--turbo-dir`, `--models-dir`) take precedence. `IMAGEGEN_LOCAL_PATHS` points to a file elsewhere. Never commit this file: it holds machine-specific paths.

- Server address: `--url`, then `unsloth_url`, then `http://localhost:8888`.
- API key: the `UNSLOTH_API_KEY` environment variable, then the file named by `--api-key-file` /
  `unsloth_api_key_file`, else none. Create the key in Unsloth under Settings → API. It is sent
  as a Bearer header and is never put on the command line, in logs or in output files.
- Keyless local access requires Settings → API → Keyless API access → "Everything else" in Unsloth.
- From another PC, start LAN access in the Unsloth UI, set a remote password, and pass the displayed network address with `--url`.

## Run

`<skill>` is the installed skill, `<repo>` this repository, `<project>` the project folder.

```powershell
python <skill>/scripts/export_scenarios.py --project <project>
python <repo>/examples/backends/unsloth/batch.py --input <project>/out/scenarios.jsonl --output <project>/results/unsloth --dry-run
python <repo>/examples/backends/unsloth/batch.py --input <project>/out/scenarios.jsonl --output <project>/results/unsloth --url http://127.0.0.1:8888 --limit 10
```

- `--limit` is the number of pending rows processed in this run; completed rows are not counted. Omit it to run everything.
- Each side of `--size` must be a positive multiple of 32 (default 1024x1024).
- `--timeout` is the socket wait per HTTP request, not a limit for the whole batch.
- `--dry-run` validates IDs, prompts, seeds and size without any network call or output.
- On Windows, use `127.0.0.1` rather than `localhost`: `localhost` may try IPv6 first and add a delay of about 2 s to each connection.

## Model loading

The batch reads the image model status. If the requested configuration is not loaded, it calls `/api/inference/images/load` and waits for status and load progress before generating. Configuration: Q8_0 GGUF, official text encoder and VAE, `memory_mode=fast`, `speed_mode=eager`, `transformer_quant=none`, `text_encoder_quant=auto`.

- Model paths are server-side paths. They are not resolved or checked on the client, so a Linux/macOS client can drive a Windows server.
- An already loaded identical configuration is reused. If a *different* model or configuration is loaded, the batch stops unless `--switch-model` is given; even then, running jobs are not interrupted.
- `model-load.json` is written atomically before the load request. If the load fails or times out (`--load-timeout`, default 1800 s), it is marked `uncertain` and the batch stops without retrying. After confirming in Unsloth that the load has fully finished or failed, move `model-load.json` aside and rerun.

## Sharing the server with other jobs

Before loading and before every generation, the batch reads the image and video generation progress, active chat generations, and training status, and stops if anything is active or the state cannot be read. The same output directory is guarded by `.batch.lock`. This does not exclude other clients or other output directories, so keep ComfyUI and other GPU apps idle. Other accounts' jobs may be invisible to the API key, so check on the host as well.

Models kept resident by other apps on the server reduce the VRAM available to Unsloth; if it spills into shared memory, generation becomes much slower.

## Output and resume

- `images/<scenario_id>.png` and `records/<scenario_id>.json`. A record stores the full input row, the request payload, the seed, the returned image URL and seed, the status, timestamps and the image SHA256. Files are written atomically.
- Rerun the same command with the same output to resume. `complete` rows are skipped after checking image existence and hash. `generated` rows only re-download the recorded URL.
- A changed input or size for an existing ID stops the batch; keep the input or use another output.
- Failures record the phase, exception type and HTTP code. Server error bodies and exception messages, which may contain secrets, are not stored.

## Timeouts and crashes (no automatic resubmission)

`submitting` is persisted before each POST. Any POST exception, including HTTP errors, marks the row `uncertain` and stops at once. A killed process may leave `submitting`. In both cases the server may still have produced the image, and the API has no request ID or idempotency key, so the next run stops before any network submission.

1. Find the generation in the Unsloth gallery or server log using the prompt, seed and time in the record. Wait while it is still running; do not stop existing jobs.
2. If you find the image, back up the record, set `response: {"images": [{"url": "/actual/gallery/path", "seed": <original seed>}]}` and change the status to `generated`. The next run will only GET it. Use the same-origin path starting with `/` returned by the server.
3. Only if you can confirm the request was never accepted or finished without output, move the record out of the output directory. The next run will POST it again.
4. If `.batch.lock` remains after a forced kill, delete only the lock once the host/pid written in it is confirmed gone (check other PCs too).

If a completed image is missing or damaged, back up its record and set the status back to `generated` to re-download it from the recorded URL. The returned data is checked for a valid PNG container; image content has to be evaluated separately.

## Portability and tests

A client only needs `batch.py`, the input JSONL, Python, and the connection settings / key file. Model files stay on the server.

```powershell
cd <repo>/examples/backends/unsloth; python -m unittest -v test_batch.py
```

The batch uses the same internal image API as the Unsloth Studio UI (payload, Bearer auth, synchronous `images[].url` response, image GET). Internal APIs may change between Unsloth versions.

Reference timing (RTX 5090): about 4 s per 1024x1024 image once the model is loaded.
