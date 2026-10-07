import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from backend import skapp_personal as bridge


class SkappPersonalBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.patches = [patch.object(bridge, 'BUNDLES', self.root / 'bundles'), patch.object(bridge, 'PYTHON', self.root / 'python'), patch.object(bridge, 'SCRIPT', self.root / 'script.py')]
        for item in self.patches:
            item.start(); self.addCleanup(item.stop)
        bridge.PYTHON.touch(); bridge.SCRIPT.touch()
        self.config = dict(metric='views', window='72h', _training_history_digest='a'*64)
        self.digest = bridge.scope_digest('owner', 'account')
        self.bundle = bridge.BUNDLES / self.digest
        self.bundle.mkdir(parents=True)
        self.manifest = dict(schema_version=1, scope_digest=self.digest, encoder_id=bridge.MODEL_NAME, feature_dim=512, target_metric='views', window_hours=72, ready_for_prediction=True, training_history_digest='a'*64, method=bridge.METHOD)
        for name in ('weights.pt', 'references.json'):
            (self.bundle / name).write_text('fixture')
        self.manifest['files'] = {name: bridge._file_digest(self.bundle / name) for name in ('weights.pt', 'references.json')}
        self.manifest['upstream_sha256'] = {name: bridge._file_digest(bridge.VENDOR / name) for name in ('model.py', 'teachers.py', 'teacher_graph.py')}
        self.write_manifest()
        self.candidates = [dict(id='one', text_vector=[1.] + [0.] * 511, image_vector=[1.] + [0.] * 511)]

    def write_manifest(self):
        (self.bundle / 'manifest.json').write_text(json.dumps(self.manifest))

    def predict(self):
        return bridge.predict('owner', 'account', self.config, self.candidates, bridge.MODEL_NAME)

    def output(self, argv, **kwargs):
        payload = json.loads(Path(argv[argv.index('--input') + 1]).read_text())
        self.assertEqual(payload['scope_digest'], self.digest)
        self.assertEqual(payload['training_history_digest'], 'a'*64)
        self.assertEqual(argv[argv.index('--bundle') + 1], str(self.bundle))
        Path(argv[argv.index('--output') + 1]).write_text(json.dumps(self.result))
        return SimpleNamespace(returncode=0)

    def successful_result(self):
        return dict(schema_version=1, status='predicted', method=bridge.METHOD, target_metric='views', window_hours=72, candidates=[dict(id='one', predicted_value=20.5, reference_ids=['ref'], rrcp=[.8], attention=[1.])], validation={'MAE': 3., 'private_path': '/secret'})

    def test_scope_isolated_and_missing_not_substituted(self):
        self.assertTrue(bridge.availability('owner', 'account', self.config)['available'])
        other = bridge.availability('other', 'account', self.config)
        self.assertEqual(other['status'], 'not_trained')
        self.assertEqual(other['predictions'], [])
        self.assertNotEqual(self.digest, bridge.scope_digest('owner', '../account'))

    def test_encoder_window_metric_manifest_mismatch(self):
        for key, value in [('encoder_id', 'other'), ('window_hours', 24), ('target_metric', 'likes'), ('scope_digest', 'other')]:
            with self.subTest(key=key):
                old = self.manifest[key]; self.manifest[key] = value; self.write_manifest()
                self.assertEqual(bridge.availability('owner', 'account', self.config)['status'], 'incompatible')
                self.manifest[key] = old
        self.write_manifest()

    def test_missing_cover_and_invalid_vector_never_execute(self):
        with patch.object(bridge.subprocess, 'run') as run:
            self.candidates[0]['image_vector'] = None
            self.assertEqual(self.predict()['status'], 'missing_cover')
            self.candidates[0]['image_vector'] = [float('nan')] * 512
            self.assertEqual(self.predict()['status'], 'invalid_input')
            run.assert_not_called()

    def test_real_subprocess_contract_and_output_whitelist(self):
        self.result = self.successful_result()
        with patch.object(bridge.subprocess, 'run', side_effect=self.output):
            result = self.predict()
        self.assertTrue(result['available'])
        self.assertEqual(result['predictions'][0]['predicted_value'], 20.5)
        self.assertEqual(result['validation'], {'MAE': 3.})
        self.assertNotIn('/secret', json.dumps(result))

    def test_attention_and_method_are_checked(self):
        for mutation in ('method', 'negative', 'sum', 'length'):
            self.result = self.successful_result()
            if mutation == 'method': self.result['method'] = 'kernel'
            elif mutation == 'negative': self.result['candidates'][0]['attention'] = [-1.]
            elif mutation == 'sum': self.result['candidates'][0]['attention'] = [.5]
            else: self.result['candidates'][0]['rrcp'] = []
            with patch.object(bridge.subprocess, 'run', side_effect=self.output):
                self.assertFalse(self.predict()['available'])

    def test_malformed_result_and_wrong_window_rejected(self):
        for mutation in ('id', 'nan', 'window'):
            self.result = self.successful_result()
            if mutation == 'id': self.result['candidates'][0]['id'] = 'other'
            elif mutation == 'nan': self.result['candidates'][0]['predicted_value'] = float('nan')
            else: self.result['window_hours'] = 24
            with patch.object(bridge.subprocess, 'run', side_effect=self.output):
                self.assertFalse(self.predict()['available'])

    def test_timeout_does_not_leak_and_releases_lock(self):
        with patch.object(bridge.subprocess, 'run', side_effect=subprocess.TimeoutExpired('/secret', 180)):
            result = self.predict()
            self.assertEqual(result['status'], 'timeout')
            self.assertEqual(self.predict()['status'], 'timeout')
        self.assertNotIn('/secret', json.dumps(result))

    def test_symlink_manifest_rejected(self):
        target = self.root / 'outside.json'; target.write_text(json.dumps(self.manifest))
        path = self.bundle / 'manifest.json'; path.unlink(); path.symlink_to(target)
        self.assertFalse(bridge.availability('owner', 'account', self.config)['available'])

    def test_training_history_change_rejects_model(self):
        for digest in ('b'*64, None, ''):
            self.config['_training_history_digest'] = digest
            with patch.object(bridge.subprocess, 'run') as run:
                self.assertEqual(self.predict()['status'], 'stale_history')
                run.assert_not_called()

    def test_missing_or_modified_artifacts_not_ready(self):
        (self.bundle / 'weights.pt').write_text('changed')
        self.assertFalse(bridge.availability('owner', 'account', self.config)['available'])
        (self.bundle / 'weights.pt').unlink()
        self.assertFalse(bridge.availability('owner', 'account', self.config)['available'])

    def test_changed_architecture_not_ready(self):
        self.manifest['upstream_sha256']['model.py'] = 'b'*64
        self.write_manifest()
        self.assertFalse(bridge.availability('owner', 'account', self.config)['available'])

    def test_synthetic_model_never_available(self):
        self.manifest['synthetic'] = True; self.write_manifest()
        self.assertFalse(bridge.availability('owner', 'account', self.config)['available'])

    def test_unvalidated_model_stays_unavailable(self):
        self.manifest['ready_for_prediction'] = False; self.write_manifest()
        self.assertEqual(bridge.availability('owner', 'account', self.config)['status'], 'trained_unvalidated')


if __name__ == '__main__':
    unittest.main()
