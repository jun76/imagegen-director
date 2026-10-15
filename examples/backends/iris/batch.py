"""Persistent local IRIS Turbo batch. Stdlib dry-run; existing IRIS venv for GPU."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time
import uuid
import urllib.error
import urllib.request

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


def now():
    return datetime.now(timezone.utc).isoformat()


def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.'+path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def save(path, obj):
    atomic(path, json.dumps(obj, ensure_ascii=False, indent=2).encode('utf-8'))


@contextmanager
def output_lock(out):
    # OS lock is released on process death. File existence does not mean busy.
    f = (out/'.batch.lock').open('a+b')
    f.seek(0)
    try:
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        raise ValueError('Another batch owns this output directory') from None
    try:
        if os.fstat(f.fileno()).st_size == 0:
            f.write(b'0')
            f.flush()
        yield
    finally:
        if os.name == 'nt':
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(f, fcntl.LOCK_UN)
        f.close()


def settings(a):
    return dict(size=a.size, steps=4, shift=4.0, dtype='bf16', attention='sdpa-expanded-gqa',
                checkpoint=str(Path(a.models_dir).resolve()/'base'),
                lora=str(Path(a.models_dir).resolve()/'turbo/r2-1000/student.safetensors'),
                text_encoder=str(Path(a.models_dir).resolve()/'text_encoder'))


def read_rows(a):
    w, h = map(int, a.size.lower().split('x'))
    if w <= 0 or h <= 0 or w % 32 or h % 32:
        raise ValueError('--size must be positive WxH multiples of 32')
    a.size = f'{w}x{h}'
    cfg = settings(a)
    rows, ids = [], set()
    with Path(a.input).open(encoding='utf-8-sig') as f:
        for line_no, line in enumerate(f, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            sid = row.get('scenario_id')
            if not isinstance(sid, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,99}', sid):
                raise ValueError(f'Invalid ID at line {line_no}')
            if sid.upper() in {'CON','PRN','AUX','NUL', *['COM'+str(i) for i in range(10)], *['LPT'+str(i) for i in range(10)]} or sid.casefold() in ids:
                raise ValueError(f'Reserved/duplicate ID at line {line_no}')
            ids.add(sid.casefold())
            if not isinstance(row.get('prompt_en'), str) or not row['prompt_en'].strip() or type(row.get('seed')) is not int or not 0 <= row['seed'] < 2**64:
                raise ValueError(f'Invalid prompt/seed at line {line_no}')
            fp = hashlib.sha256(json.dumps([row,cfg], sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()
            rows.append((sid,row,fp))
    return rows, cfg, w, h


def api(url, key, method, path, allow_refused=False):
    headers = {'Authorization': 'Bearer '+key} if key else {}
    req = urllib.request.Request(url.rstrip('/')+path, method=method, headers=headers,
                                 data=b'{}' if method == 'POST' else None)
    if method == 'POST':
        req.add_header('Content-Type','application/json')
    # Do not print server bodies/URLs (could echo credentials).
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read())
    except urllib.error.URLError as e:
        if allow_refused and isinstance(e.reason, ConnectionRefusedError):
            return None
        raise ValueError(f'GPU idle check failed at {path}: {type(e.reason).__name__}; no process interrupted') from None
    except Exception as e:
        raise ValueError(f'GPU idle check failed: {type(e).__name__}; HTTP {getattr(e,"code",None)}') from None


def api_key(key_file):
    """Unsloth API key: $UNSLOTH_API_KEY, else the file named by --unsloth-api-key-file / unsloth_api_key_file."""
    key = os.environ.get('UNSLOTH_API_KEY', '').strip()
    if not key and key_file:
        key = Path(key_file).expanduser().read_text(encoding='utf-8').strip()
    return key


def prepare_gpu(a):
    # Nothing configured: plain localhost without a key.
    url = a.unsloth_url or 'http://localhost:8888'
    key = api_key(a.unsloth_api_key_file)
    # A refused connection means the server is not running, so it holds no GPU memory.
    # Timeouts and other errors still stop the batch (state unknown).
    unsloth_running = True
    for path, field in [('/api/inference/images/generate-progress','active'),
                        ('/api/inference/video/generate-progress','active'),
                        ('/api/inference/active-generations','count'),
                        ('/api/train/status','is_training_running')]:
        s = api(url,key,'GET',path,allow_refused=True)
        if s is None:
            unsloth_running = False
            print('Unsloth not running (connection refused); skipping its checks.',file=sys.stderr,flush=True)
            break
        if field not in s or s[field]:
            raise ValueError('Unsloth busy or idle state unknown; no process interrupted')
    queue = api(a.comfy_url,'','GET','/queue',allow_refused=True)
    if queue is not None and ('queue_running' not in queue or 'queue_pending' not in queue or queue['queue_running'] or queue['queue_pending']):
        raise ValueError('ComfyUI busy or idle state unknown; no process interrupted')
    if not unsloth_running:
        return
    status = api(url,key,'GET','/api/inference/images/status')
    if status.get('loaded'):
        # User-authorized idle image model release only. No other model/server is stopped.
        api(url,key,'POST','/api/inference/images/unload')
        if api(url,key,'GET','/api/inference/images/status').get('loaded'):
            raise ValueError('Unsloth image model did not unload')
        print('Released idle Unsloth image model.',file=sys.stderr,flush=True)


class Engine:
    def __init__(self, a, cfg):
        os.environ['HF_HUB_DISABLE_PROGRESS_BARS'] = '1'
        os.environ['HF_HUB_OFFLINE'] = '1'
        os.environ['TRANSFORMERS_OFFLINE'] = '1'
        sys.path.insert(0,str(Path(a.iris_source).resolve()/'src'))
        import torch
        import iris3b.text
        from iris3b.config import inference_config
        from iris3b.sampling import read_config, load_model_streaming
        from iris3b.registry import TEXT_ENCODERS
        from iris3b.devices import inference_autocast
        from iris3b.distill import generate_turbo
        import iris3b.nn.attention as attention
        original = attention.scaled_dot_product
        def expanded(q,k,v,backend='sdpa',attn_mask=None,enable_gqa=False):
            if backend == 'sdpa' and enable_gqa and q.shape[-3] != k.shape[-3]:
                groups = q.shape[-3]//k.shape[-3]
                k = k.repeat_interleave(groups,dim=-3)
                v = v.repeat_interleave(groups,dim=-3)
                enable_gqa = False
            return original(q,k,v,backend,attn_mask,enable_gqa)
        for module in list(sys.modules.values()):
            if getattr(module,'__name__','').startswith('iris3b') and getattr(module,'scaled_dot_product',None) is original:
                module.scaled_dot_product = expanded
        self.torch, self.device = torch, torch.device('cuda')
        if not torch.cuda.is_available():
            raise ValueError('Existing IRIS venv must have working CUDA')
        free, total = torch.cuda.mem_get_info()
        if free < 16*1024**3:
            raise ValueError('Less than 16 GiB free VRAM; release other idle models manually')
        config = inference_config(read_config(cfg['checkpoint']),['text_encoder.pretrained='+cfg['text_encoder']])
        self.encoder = TEXT_ENCODERS.build(config.text_encoder.name,config.text_encoder,device=self.device)
        self.model,meta = load_model_streaming(config.model,cfg['checkpoint'],self.device,torch.bfloat16,None,cfg['lora'],1.0)
        if int(meta.get('turbo_steps',0)) != 4 or float(meta.get('shift',0)) != 4:
            raise ValueError('Expected r2-1000 4-step shift4 Turbo adapter')
        for module in self.model.modules():
            if getattr(module,'backend',None) in ('sdpa','torch_cudnn','torch_flash'):
                module.backend = 'sdpa'
        self.autocast, self.generate = inference_autocast, generate_turbo
        self.encoding_seconds = 0
        original_encode = self.encoder.encode
        def timed_encode(prompts):
            torch.cuda.synchronize()
            t = time.perf_counter()
            result = original_encode(prompts)
            torch.cuda.synchronize()
            self.encoding_seconds = time.perf_counter()-t
            return result
        self.encoder.encode = timed_encode
        torch.cuda.synchronize()
        self.info = dict(gpu=torch.cuda.get_device_name(),torch=torch.__version__,free_vram_before_load=free,total_vram=total)

    def image(self,row,w,h):
        from PIL import Image
        t = self.torch
        generator = t.Generator(device=self.device).manual_seed(row['seed'])
        t.cuda.synchronize()
        start = time.perf_counter()
        with t.inference_mode(),self.autocast(self.device):
            result = self.generate(self.model,self.encoder,[row['prompt_en']],h,w,4,4.0,generator,self.device)
        result = result.cpu()
        t.cuda.synchronize()
        elapsed = time.perf_counter()-start
        pixels = ((result[0].float().clamp(-1,1)+1)*127.5).round().byte().permute(1,2,0).numpy()
        return Image.fromarray(pixels),dict(generation_seconds=elapsed,text_encode_seconds=self.encoding_seconds)


def decode(path):
    from PIL import Image
    with Image.open(path) as image:
        if image.format != 'PNG':
            raise ValueError('Not PNG')
        image.verify()
    with Image.open(path) as image:
        image.load()
        return image.size, json.loads(image.info['iris_batch_record'])


def run(a, engine_factory=Engine, gpu_check=prepare_gpu):
    start = time.perf_counter()
    rows,cfg,w,h = read_rows(a)
    if a.dry_run:
        print(json.dumps(dict(validated=len(rows),limit=a.limit,size=a.size,steps=4,shift=4,gpu_calls=0)))
        return 0
    out = Path(a.output).resolve()
    out.mkdir(parents=True,exist_ok=True)
    with output_lock(out):
        pending, recovered = [], []
        for sid,row,fp in rows:
            image, rp = out/'images'/(sid+'.png'),out/'records'/(sid+'.json')
            record = json.loads(rp.read_text(encoding='utf-8')) if rp.exists() else None
            if record and record['fingerprint'] != fp:
                raise ValueError(sid+': input/settings changed; use a new output')
            if image.exists():
                size,embedded = decode(image)
                digest = hashlib.sha256(image.read_bytes()).hexdigest()
                if embedded['fingerprint'] != fp or size != (w,h):
                    raise ValueError(sid+': image input/settings mismatch')
                if record and record.get('status') == 'complete' and record.get('sha256') != digest:
                    raise ValueError(sid+': completed image hash mismatch')
                if not record or record.get('status') != 'complete':
                    record = dict(embedded,status='complete',sha256=digest,recovered_at=now())
                    save(rp,record)
                    recovered.append(sid)
                continue
            if record and record.get('status') == 'complete':
                raise ValueError(sid+': completed image missing; restore image or use a new output')
            pending.append((sid,row,fp))
        selected = pending[:a.limit] if a.limit else pending
        if not selected:
            print('All selected inputs already complete.',file=sys.stderr)
            return 0
        for path in [Path(cfg['checkpoint'])/'config.yaml',Path(cfg['checkpoint'])/'model.safetensors',Path(cfg['lora']),Path(cfg['text_encoder'])/'config.json']:
            if not path.is_file():
                raise ValueError('Missing local model file: '+str(path))
        gpu_check(a)
        load_start = time.perf_counter()
        print('Loading IRIS model, merged Turbo LoRA and encoder once...',file=sys.stderr,flush=True)
        engine = engine_factory(a,cfg)
        load_seconds = time.perf_counter()-load_start
        runid = uuid.uuid4().hex
        report = dict(run_id=runid,started_at=now(),settings=cfg,load_seconds=load_seconds,engine=engine.info,recovered=recovered,images=[],status='running')
        report_path = out/'runs'/(runid+'.json')
        save(report_path,report)
        from PIL.PngImagePlugin import PngInfo
        for sid,row,fp in selected:
            rp,image_path = out/'records'/(sid+'.json'),out/'images'/(sid+'.png')
            record = dict(scenario=row,settings=cfg,fingerprint=fp,status='generating',run_id=runid,started_at=now())
            save(rp,record)
            try:
                image,timing = engine.image(row,w,h)
                record.update(timing,completed_at=now())
                meta = PngInfo()
                meta.add_text('iris_batch_record',json.dumps(record,ensure_ascii=False))
                buffer = io.BytesIO()
                image.save(buffer,format='PNG',pnginfo=meta)
                content = buffer.getvalue()
                atomic(image_path,content)
                # PNG itself contains enough provenance to repair a crash before sidecar save.
                size,embedded = decode(image_path)
                if size != (w,h) or embedded['fingerprint'] != fp:
                    raise ValueError('Saved PNG verification failed')
                record.update(status='complete',sha256=hashlib.sha256(content).hexdigest(),image=str(image_path))
                save(rp,record)
                report['images'].append(dict(scenario_id=sid,seed=row['seed'],sha256=record['sha256'],**timing))
                save(report_path,report)
                print(f'{sid}: {timing["generation_seconds"]:.3f}s (text {timing["text_encode_seconds"]:.3f}s)',file=sys.stderr,flush=True)
                print(str(image_path),flush=True)
            except BaseException as exc:
                record.update(status='failed',failure_type=type(exc).__name__)
                save(rp,record)
                report.update(status='failed',failure_type=type(exc).__name__,elapsed_seconds=time.perf_counter()-start)
                save(report_path,report)
                raise
        report.update(status='complete',exit_code=0,processed_count=len(report['images']),finished_at=now(),elapsed_seconds=time.perf_counter()-start)
        save(report_path,report)
        print(f'Completed {len(report["images"])} images; load {load_seconds:.3f}s; total {report["elapsed_seconds"]:.3f}s.',file=sys.stderr,flush=True)
        return 0


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',required=True)
    p.add_argument('--output',required=True)
    p.add_argument('--limit',type=int)
    p.add_argument('--size',default='1024x1024')
    p.add_argument('--dry-run',action='store_true')
    local = local_paths()
    p.add_argument('--runtime-python',default=local.get('iris_python'),help='Python of an existing IRIS venv')
    p.add_argument('--iris-source',default=local.get('iris_source'),help='IRIS checkout (parent of src)')
    p.add_argument('--models-dir',default=local.get('iris_models_dir'),help='IRIS model root (base/, turbo/, text_encoder/)')
    p.add_argument('--unsloth-url',default=local.get('unsloth_url'),help='Unsloth server address for the GPU idle check (default http://localhost:8888)')
    p.add_argument('--unsloth-api-key-file',default=local.get('unsloth_api_key_file'),help='file containing only the Unsloth API key; $UNSLOTH_API_KEY takes precedence')
    p.add_argument('--comfy-url',default=local.get('comfy_url','http://127.0.0.1:8000'))
    a = p.parse_args()
    if a.limit is not None and a.limit <= 0:
        p.error('--limit must be positive')
    missing = [f for f in ('runtime_python','iris_source','models_dir') if not getattr(a,f)]
    if missing and not a.dry_run:
        p.error('set '+', '.join('--'+f.replace('_','-') for f in missing)+' or add them to local_paths.json')
    a.models_dir = a.models_dir or 'unset'
    # Validate before starting another interpreter; dry-run imports no GPU libraries.
    read_rows(a)
    if not a.dry_run and Path(sys.executable).resolve() != Path(a.runtime_python).resolve():
        if not Path(a.runtime_python).is_file():
            raise ValueError('Existing IRIS Python not found; set --runtime-python')
        return subprocess.call([a.runtime_python,str(Path(__file__).resolve()),*sys.argv[1:]])
    return run(a)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print('Interrupted; completed PNGs will be recovered/skipped on resume.',file=sys.stderr)
        sys.exit(130)
    except Exception as exc:
        print('ERROR: '+str(exc) if isinstance(exc,ValueError) else 'ERROR: '+type(exc).__name__,file=sys.stderr)
        sys.exit(1)
