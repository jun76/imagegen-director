#!/usr/bin/env python3
"""Sequential, crash-conservative Unsloth image batch client. Python 3.10+."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from pathlib import PurePosixPath
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

ENDPOINT = '/api/inference/images/generate'


def load_payload(args):
    # Server paths: never resolve or test them on the client (which may be another OS).
    turbo = args.turbo_dir.replace('\\', '/').rstrip('/')
    models = args.models_dir.replace('\\', '/').rstrip('/')
    return dict(model_path=turbo, gguf_filename='qwen-image-2.1-turbo-Q8_0.gguf',
                model_kind='gguf', display_repo_id='unsloth/Qwen-Image-2.1-Turbo-GGUF',
                family_override='qwen-image-2.1', base_repo='Qwen/Qwen-Image-2.1-Turbo',
                text_encoder_file=models+'/text_encoders/qwen3vl_8b_int8_convrot.safetensors',
                vae_file=turbo+'/qwen_image_2.1_vae_bf16.safetensors', memory_mode='fast',
                speed_mode='eager', transformer_quant='none', text_encoder_quant='auto')


def local_paths():
    """Machine-specific defaults (model paths, venv, server config). Never commit this file.

    Looked up in order: $IMAGEGEN_LOCAL_PATHS, ./local_paths.json (current directory),
    ~/.config/imagegen-director/local_paths.json. CLI flags take precedence over its values.
    """
    candidates = [os.environ.get('IMAGEGEN_LOCAL_PATHS'), 'local_paths.json',
                  Path.home()/'.config/imagegen-director/local_paths.json']
    for c in candidates:
        if c and Path(c).is_file():
            return json.loads(Path(c).read_text(encoding='utf-8'))
    return {}


def api_key(key_file):
    """Unsloth API key: $UNSLOTH_API_KEY, else the file named by --api-key-file / unsloth_api_key_file."""
    key = os.environ.get('UNSLOTH_API_KEY', '').strip()
    if not key and key_file:
        key = Path(key_file).expanduser().read_text(encoding='utf-8').strip()
    return key


def matches(status, payload):
    components = status.get('component_files') or {}
    return bool(status.get('loaded') and
                all(status.get(k) == payload[k] for k in ('gguf_filename', 'base_repo', 'model_kind', 'memory_mode', 'speed_mode')) and
                components.get('text_encoder') == PurePosixPath(payload['text_encoder_file']).name and
                components.get('vae') == PurePosixPath(payload['vae_file']).name)


def check_idle(client):
    checks = [('/api/inference/images/generate-progress', 'active'),
              ('/api/train/status', 'is_training_running'),
              ('/api/inference/active-generations', 'count'),
              ('/api/inference/video/generate-progress', 'active')]
    for path, key in checks:
        state = client.request('GET', path)
        if key not in state:
            raise ValueError('Cannot verify idle state at ' + path + '; no load/generation submitted')
        if state[key] or (path.endswith('active-generations') and state.get('active')):
            raise ValueError('Unsloth has active work; no load/generation submitted')


def ensure_model(client, args, out):
    payload = load_payload(args)
    status = client.request('GET', '/api/inference/images/status')
    check_idle(client)
    if matches(status, payload):
        return
    marker = out / 'model-load.json'
    if marker.exists():
        prior = json.loads(marker.read_text(encoding='utf-8'))
        if prior.get('status') in ('submitting', 'uncertain', 'waiting'):
            raise ValueError('Previous model load unresolved; inspect Unsloth and model-load.json before retry. No repeated load submitted.')
    progress = client.request('GET', '/api/inference/images/load-progress')
    if 'phase' not in progress or progress['phase'] not in (None, 'complete', 'completed', 'done', 'idle', 'ready', 'error'):
        raise ValueError('An image model load is in progress or its state is unknown; no load submitted')
    if status.get('loaded') and not args.switch_model:
        raise ValueError('A different image model/configuration is loaded; use --switch-model explicitly after confirming it may be replaced')
    record = dict(status='submitting', payload=payload)
    save(marker, record)
    try:
        # Same payload/endpoint as load_qwen21.py. No force/cancel/unload request.
        client.request('POST', '/api/inference/images/load', payload)
        record['status'] = 'waiting'
        save(marker, record)
        deadline = time.monotonic() + args.load_timeout
        while True:
            status = client.request('GET', '/api/inference/images/status')
            if matches(status, payload):
                record['status'] = 'complete'
                save(marker, record)
                check_idle(client)
                return
            progress = client.request('GET', '/api/inference/images/load-progress')
            if progress.get('phase') == 'error':
                raise ValueError('Server reports model load failure')
            if time.monotonic() >= deadline:
                raise TimeoutError()
            time.sleep(min(3, max(0, deadline-time.monotonic())))
    except BaseException as exc:
        record.update(status='uncertain', failure={'type': type(exc).__name__, 'http_status': getattr(exc, 'code', None)})
        save(marker, record)
        raise ValueError('Model load failed or timed out; inspect Unsloth/model-load.json. No automatic retry or generation submitted.') from None


def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def save(path, record):
    record['updated_at'] = datetime.now(timezone.utc).isoformat()
    atomic(path, json.dumps(record, ensure_ascii=False, indent=2).encode('utf-8'))


def png(data):
    if len(data) < 33 or data[:8] != b'\x89PNG\r\n\x1a\n' or data[12:16] != b'IHDR' or b'IEND' not in data[-12:]:
        raise ValueError('Invalid PNG container')
    return data


class Client:
    def __init__(self, url, key, timeout):
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('URL must be an HTTP(S) origin without credentials/query/fragment')
        self.url, self.key, self.timeout = url.rstrip('/'), key, timeout
        # Do not follow redirects with Authorization, or send credentials to response-provided hosts.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        self.opener = urllib.request.build_opener(NoRedirect)

    def request(self, method, path, payload=None, raw=False):
        if not isinstance(path, str) or not path.startswith('/') or path.startswith('//'):
            raise ValueError('API response image URL must be same-origin relative path')
        data = None if payload is None else json.dumps(payload).encode('utf-8')
        headers = {'Content-Type': 'application/json'} if data else {}
        if self.key:
            headers['Authorization'] = 'Bearer ' + self.key
        req = urllib.request.Request(self.url + path, data=data, headers=headers, method=method)
        with self.opener.open(req, timeout=self.timeout) as response:
            body = response.read()
        return body if raw else json.loads(body)


def read_input(path, size):
    rows, ids = [], set()
    with path.open(encoding='utf-8-sig') as f:
        for line_no, line in enumerate(f, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            sid = row.get('scenario_id')
            if not isinstance(sid, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,99}', sid) or sid.upper() in {'CON', 'PRN', 'AUX', 'NUL', *['COM'+str(i) for i in range(10)], *['LPT'+str(i) for i in range(10)]}:
                raise ValueError(f'Invalid scenario_id at line {line_no}')
            if sid.casefold() in ids:
                raise ValueError(f'Duplicate scenario_id at line {line_no}')
            ids.add(sid.casefold())
            if not isinstance(row.get('prompt_en'), str) or not row['prompt_en'].strip() or type(row.get('seed')) is not int:
                raise ValueError(f'Invalid prompt/seed at line {line_no}')
            payload = dict(prompt=row['prompt_en'], seed=row['seed'], steps=8, guidance=1.0, width=size[0], height=size[1])
            fingerprint = hashlib.sha256(json.dumps([row, payload], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            rows.append((sid, row, payload, fingerprint))
    return rows


def run(args, client=None):
    try:
        size = tuple(int(x) for x in args.size.lower().split('x'))
        if len(size) != 2 or any(x <= 0 or x % 32 for x in size):
            raise ValueError()
    except ValueError:
        raise ValueError('--size must be positive WxH multiples of 32')
    rows = read_input(Path(args.input), size)
    out = Path(args.output).resolve()
    if args.dry_run:
        print(json.dumps({'validated': len(rows), 'selected_max': min(len(rows), args.limit or len(rows)), 'size': size, 'steps': 8, 'guidance': 1.0, 'network_calls': 0}))
        return 0
    out.mkdir(parents=True, exist_ok=True)
    lock = out / '.batch.lock'
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.write(fd, json.dumps({'pid': os.getpid(), 'host': __import__('socket').gethostname()}).encode())
    os.close(fd)
    try:
        states = {}
        for sid, row, payload, fingerprint in rows:
            sp = out / 'records' / (sid + '.json')
            if sp.exists():
                record = json.loads(sp.read_text(encoding='utf-8'))
                if record['fingerprint'] != fingerprint:
                    raise ValueError(f'{sid}: input/settings changed; use another output directory')
                states[sid] = record
        unknown = [sid for sid, record in states.items() if record['status'] in ('submitting', 'uncertain')]
        if unknown:
            raise ValueError('Unresolved POST(s): ' + ', '.join(unknown) + '; see README recovery instructions')
        if client is None:
            # Nothing configured: plain localhost without a key.
            client = Client(args.url or 'http://localhost:8888', api_key(args.api_key_file), args.timeout)
        ensure_model(client, args, out)
        count = 0
        for sid, row, payload, fingerprint in rows:
            record = states.get(sid)
            sp, image = out / 'records' / (sid + '.json'), out / 'images' / (sid + '.png')
            if record and record['status'] == 'complete':
                if not image.exists() or hashlib.sha256(image.read_bytes()).hexdigest() != record['sha256']:
                    raise ValueError(f'{sid}: completed image missing/changed; recover from recorded URL')
                continue
            if args.limit and count >= args.limit:
                break
            count += 1
            if record is None:
                check_idle(client)
                if image.exists():
                    raise ValueError(f'{sid}: untracked image exists')
                record = dict(scenario=row, payload=payload, fingerprint=fingerprint, status='submitting')
                save(sp, record)  # durable intent before POST; crash here is conservatively unresolved
                try:
                    response = client.request('POST', ENDPOINT, payload)
                    record['response'] = response
                    record['status'] = 'generated'
                    save(sp, record)
                except BaseException as exc:
                    record['status'] = 'uncertain'
                    record['failure'] = {'phase': 'post', 'type': type(exc).__name__, 'http_status': getattr(exc, 'code', None)}
                    save(sp, record)
                    raise ValueError(f'{sid}: POST outcome uncertain; stopped without retry') from None
            try:
                images = record['response'].get('images') or []
                if len(images) != 1:
                    raise ValueError('Expected exactly one returned image')
                content = png(client.request('GET', images[0]['url'], raw=True))
                atomic(image, content)
                record.update(status='complete', sha256=hashlib.sha256(content).hexdigest(), image=str(image), returned_seed=images[0].get('seed'))
                record.pop('failure', None)
                save(sp, record)
                print(str(image))
            except Exception as exc:
                record['failure'] = {'phase': 'download', 'type': type(exc).__name__, 'http_status': getattr(exc, 'code', None)}
                save(sp, record)
                raise ValueError(f'{sid}: download/save failed; resume will GET recorded URL only') from None
        return 0
    finally:
        lock.unlink()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', required=True)
    p.add_argument('--output', required=True)
    local = local_paths()
    p.add_argument('--url', default=local.get('unsloth_url'), help='Unsloth server address (default http://localhost:8888)')
    p.add_argument('--api-key-file', default=local.get('unsloth_api_key_file'),
                   help='file containing only the API key; $UNSLOTH_API_KEY takes precedence. Never pass the key itself')
    p.add_argument('--size', default='1024x1024')
    p.add_argument('--timeout', type=float, default=3600)
    p.add_argument('--load-timeout', type=float, default=1800)
    p.add_argument('--turbo-dir', default=local.get('unsloth_turbo_dir'), help='Server-side Qwen-Image 2.1 Turbo GGUF directory')
    p.add_argument('--models-dir', default=local.get('unsloth_models_dir'), help='Server-side models root containing text_encoders/')
    p.add_argument('--switch-model', action='store_true', help='Allow replacing a different idle image model/configuration')
    p.add_argument('--limit', type=int)
    p.add_argument('--dry-run', action='store_true')
    a = p.parse_args()
    if a.timeout <= 0 or a.load_timeout <= 0 or (a.limit is not None and a.limit <= 0):
        p.error('--timeout and --limit must be positive')
    if not a.dry_run and not (a.turbo_dir and a.models_dir):
        p.error('set --turbo-dir and --models-dir or add them to local_paths.json')
    try:
        return run(a)
    except Exception as exc:
        # Network exceptions may contain URLs or echoed secrets: never print their bodies.
        message = str(exc) if isinstance(exc, (ValueError, FileExistsError)) else type(exc).__name__
        print('ERROR: ' + message, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
