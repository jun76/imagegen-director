import argparse
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
import batch


class FakeEngine:
    calls = 0
    def __init__(self, a, cfg):
        self.info = {'gpu':'mock'}
    def image(self, row, w, h):
        FakeEngine.calls += 1
        return Image.new('RGB',(w,h),'red'), {'generation_seconds':0.1,'text_encode_seconds':0.01}


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        models = self.root/'models'
        for rel in ['base/config.yaml','base/model.safetensors','turbo/r2-1000/student.safetensors','text_encoder/config.json']:
            path = models/rel
            path.parent.mkdir(parents=True,exist_ok=True)
            path.touch()
        self.row = {'scenario_id':'S00001','prompt_en':'Original prompt','seed':42,'category':'test'}
        self.input = self.root/'scenarios.jsonl'
        self.input.write_text(json.dumps(self.row))
        self.a = argparse.Namespace(input=str(self.input),output=str(self.root/'results'),limit=1,size='1024x1024',dry_run=False,models_dir=str(models))
        FakeEngine.calls = 0
    def tearDown(self):
        self.temp.cleanup()
    def run_batch(self):
        return batch.run(self.a,FakeEngine,lambda a:None)
    def test_resume_and_embedded_recovery(self):
        self.run_batch()
        self.run_batch()
        self.assertEqual(FakeEngine.calls,1)
        record = self.root/'results/records/S00001.json'
        record.unlink() # simulate crash after PNG atomic commit but before record save
        self.run_batch()
        self.assertEqual(FakeEngine.calls,1)
        self.assertEqual(json.loads(record.read_text())['status'],'complete')
    def test_changed_input(self):
        self.run_batch()
        self.row['seed'] = 43
        self.input.write_text(json.dumps(self.row))
        with self.assertRaisesRegex(ValueError,'changed'):
            self.run_batch()
    def test_dry_run_and_lock(self):
        self.a.dry_run = True
        batch.run(self.a,lambda *args: self.fail('loaded GPU'),lambda *args:self.fail('network'))
        self.assertFalse((self.root/'results').exists())
        self.a.dry_run = False
        out = Path(self.a.output)
        out.mkdir()
        with batch.output_lock(out):
            with self.assertRaisesRegex(ValueError,'owns'):
                self.run_batch()
    def test_failed_local_generation_retry(self):
        class Fail(FakeEngine):
            def image(self,*args):
                raise RuntimeError('mock')
        with self.assertRaises(RuntimeError):
            batch.run(self.a,Fail,lambda a:None)
        self.run_batch()
        self.assertEqual(FakeEngine.calls,1)
    def test_busy_refuses_unload(self):
        self.a.unsloth_url = None
        self.a.unsloth_api_key_file = None
        self.a.comfy_url = 'http://localhost:8000'
        with patch('batch.api',return_value={'active':True}) as api:
            with self.assertRaisesRegex(ValueError,'busy'):
                batch.prepare_gpu(self.a)
            self.assertEqual(api.call_count,1)


if __name__ == '__main__':
    unittest.main()
