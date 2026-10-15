import argparse
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import batch

PNG = bytes.fromhex('89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000b49444154789c636000020000050001a5f645400000000049454e44ae426082')


class Mock:
    def __init__(self, fail=None):
        self.calls, self.fail = [], fail

    def request(self, method, path, payload=None, raw=False):
        self.calls.append((method, path, payload))
        if path == '/api/inference/images/status':
            return {'loaded': True, 'base_repo': 'Qwen/Qwen-Image-2.1-Turbo', 'gguf_filename': 'qwen-image-2.1-turbo-Q8_0.gguf', 'model_kind': 'gguf', 'memory_mode': 'fast', 'speed_mode': 'eager', 'component_files': {'text_encoder': 'qwen3vl_8b_int8_convrot.safetensors', 'vae': 'qwen_image_2.1_vae_bf16.safetensors'}}
        if path == '/api/train/status':
            return {'is_training_running': False}
        if path.endswith('/active-generations'):
            return {'count': 0, 'active': []}
        if path.endswith('/generate-progress'):
            return {'active': False}
        if path.endswith('/load-progress'):
            return {'phase': None, 'fraction': 0.0}
        if method == 'POST':
            if self.fail == 'post':
                raise TimeoutError('secret must not be logged')
            return {'images': [{'url': '/gallery/image.png', 'seed': 42}]}
        if self.fail == 'download':
            raise OSError('download')
        return PNG


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / 'input.jsonl'
        self.row = {'scenario_id': 'S00001', 'prompt_en': 'Exact original prompt.', 'seed': 42, 'category': 'test'}
        self.source.write_text(json.dumps(self.row)+'\n', encoding='utf-8')
        self.args = argparse.Namespace(input=str(self.source), output=str(self.root/'out'), size='1024x1024', dry_run=False, limit=None, api_key_file=None, url=None, timeout=1)
        self.args.turbo_dir = 'C:/models/unsloth/Qwen-Image-2.1-Turbo-GGUF/Q8_0'
        self.args.models_dir = 'D:/models'
        self.args.load_timeout = 1
        self.args.switch_model = False

    def tearDown(self):
        self.temp.cleanup()

    def test_api_key_env_then_file(self):
        keyfile = self.root / 'key.txt'
        keyfile.write_text('file-key\n', encoding='utf-8')
        with patch.dict(os.environ, {'UNSLOTH_API_KEY': ''}):
            self.assertEqual(batch.api_key(None), '')
            self.assertEqual(batch.api_key(str(keyfile)), 'file-key')
        with patch.dict(os.environ, {'UNSLOTH_API_KEY': 'env-key'}):
            self.assertEqual(batch.api_key(str(keyfile)), 'env-key')

    def test_success_resume_payload(self):
        client = Mock()
        batch.run(self.args, client)
        batch.run(self.args, client)
        posts = [c for c in client.calls if c[0] == 'POST']
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0][2]['prompt'], self.row['prompt_en'])
        self.assertEqual(posts[0][2]['seed'], 42)
        self.assertEqual(posts[0][2]['steps'], 8)

    def test_uncertain_blocks_all_subsequent_posts(self):
        with self.assertRaises(ValueError):
            batch.run(self.args, Mock('post'))
        client = Mock()
        with self.assertRaises(ValueError):
            batch.run(self.args, client)
        self.assertEqual(client.calls, [])

    def test_download_resume_does_not_post(self):
        with self.assertRaises(ValueError):
            batch.run(self.args, Mock('download'))
        client = Mock()
        batch.run(self.args, client)
        self.assertFalse(any(c[0] == 'POST' for c in client.calls))

    def test_dry_no_network_or_output(self):
        self.args.dry_run = True
        with patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('network')):
            batch.run(self.args)
        self.assertFalse((self.root/'out').exists())

    def test_bad_size_and_duplicate(self):
        self.args.size = '1000x1024'
        with self.assertRaises(ValueError):
            batch.run(self.args, Mock())
        self.args.size = '1024x1024'
        self.source.write_text((json.dumps(self.row)+'\n')*2)
        with self.assertRaises(ValueError):
            batch.run(self.args, Mock())

    def test_lock_and_changed_input(self):
        batch.run(self.args, Mock())
        lock = self.root/'out/.batch.lock'
        lock.touch()
        with self.assertRaises(FileExistsError):
            batch.run(self.args, Mock())
        lock.unlink()
        self.row['seed'] = 43
        self.source.write_text(json.dumps(self.row))
        with self.assertRaises(ValueError):
            batch.run(self.args, Mock())

    def test_load_reuse_switch_busy_timeout(self):
        class Loader(Mock):
            def __init__(self, loaded=False, busy=False, timeout=False):
                super().__init__()
                self.loaded, self.busy, self.timeout = loaded, busy, timeout
            def request(self, method, path, payload=None, raw=False):
                if path.endswith('/images/status') and self.loaded is not True:
                    self.calls.append((method, path, payload))
                    return {'loaded': bool(self.loaded), 'base_repo': 'other'}
                if path.endswith('/generate-progress') and self.busy:
                    return {'active': True}
                if path.endswith('/images/load'):
                    self.calls.append((method, path, payload))
                    if self.timeout:
                        raise TimeoutError()
                    self.loaded = True
                    return {}
                return super().request(method, path, payload, raw)
        client = Loader()
        batch.run(self.args, client)
        loads = [c for c in client.calls if c[1].endswith('/images/load')]
        self.assertEqual(len(loads), 1)
        self.assertEqual(loads[0][2], batch.load_payload(self.args))
        self.assertEqual(loads[0][2]['memory_mode'], 'fast')
        # Test loader directly in separate output folders, preserving generation states.
        for name, client, expected in [('busy', Loader(busy=True), 'active work'), ('other', Loader(loaded='other'), 'different image model'), ('timeout', Loader(timeout=True), 'timed out')]:
            out = self.root/name
            out.mkdir()
            with self.assertRaisesRegex(ValueError, expected):
                batch.ensure_model(client, self.args, out)
            if name != 'timeout':
                self.assertFalse(any(c[0] == 'POST' for c in client.calls))
            else:
                fresh = Loader()
                with self.assertRaisesRegex(ValueError, 'unresolved'):
                    batch.ensure_model(fresh, self.args, out)
                self.assertFalse(any(c[0] == 'POST' for c in fresh.calls))
        self.args.switch_model = True
        client = Loader(loaded='other')
        out = self.root/'switch'
        out.mkdir()
        batch.ensure_model(client, self.args, out)
        self.assertEqual(len([c for c in client.calls if c[0] == 'POST']), 1)


if __name__ == '__main__':
    unittest.main()
