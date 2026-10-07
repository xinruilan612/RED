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
        self.config = dict(platform='xiaohongshu', metric='views', window='72h')
        self.profile = [1.] + [0.] * 511
        self.digest = bridge.scope_digest('owner', 'account')
        self.bundle = bridge.BUNDLES / 'xiaohongshu' / 'views-72h'
        self.bundle.mkdir(parents=True)
        self.manifest = dict(schema_version=1, model_scope='shared', data_scope='licensed_public', dataset_license='Test fixture only', corpus_fingerprint='c'*64, platform='xiaohongshu', encoder_id=bridge.MODEL_NAME, feature_dim=512, target_metric='views', window_hours=72, ready_for_prediction=True, method=bridge.METHOD)
        for name in ('weights.pt', 'references.json', 'corpus.json'):
            (self.bundle / name).write_text('fixture')
        from scripts.skapp_personal import corpus_fingerprint
        corpus = {key: self.manifest[key] for key in ('schema_version', 'model_scope', 'data_scope', 'encoder_id', 'platform', 'target_metric', 'window_hours', 'dataset_license')}
        corpus['records'] = []
        (self.bundle / 'corpus.json').write_text(json.dumps(corpus))
        self.manifest['corpus_fingerprint'] = corpus_fingerprint(corpus)
        self.manifest['files'] = {name: bridge._file_digest(self.bundle / name) for name in ('weights.pt', 'references.json', 'corpus.json')}
        self.manifest['upstream_sha256'] = {name: bridge._file_digest(bridge.VENDOR / name) for name in ('model.py', 'teachers.py', 'teacher_graph.py')}
        self.write_manifest()
        self.candidates = [dict(id='one', text_vector=[1.] + [0.] * 511, image_vector=[1.] + [0.] * 511)]

    def write_manifest(self):
        (self.bundle / 'manifest.json').write_text(json.dumps(self.manifest))

    def predict(self):
        return bridge.predict('owner', 'account', self.config, self.candidates, bridge.MODEL_NAME, profile_vector=self.profile)

    def output(self, argv, **kwargs):
        payload = json.loads(Path(argv[argv.index('--input') + 1]).read_text())
        self.assertEqual(payload['author_id'], 'web:' + self.digest)
        self.assertEqual(payload['profile_vector'], self.profile)
        self.assertNotIn('training_history_digest', payload)
        self.assertNotIn('history', payload)
        self.assertEqual(argv[argv.index('--bundle') + 1], str(self.bundle))
        Path(argv[argv.index('--output') + 1]).write_text(json.dumps(self.result))
        return SimpleNamespace(returncode=0)

    def successful_result(self):
        return dict(schema_version=1, status='predicted', method=bridge.METHOD, target_metric='views', window_hours=72, candidates=[dict(id='one', predicted_value=20.5, reference_ids=['ref'], rrcp=[.8], attention=[1.])], validation={'MAE': 3., 'private_path': '/secret'})

    def test_model_shared_while_author_identity_isolated(self):
        self.assertTrue(bridge.availability('owner', 'account', self.config)['available'])
        other = bridge.availability('other', 'account', self.config)
        self.assertEqual(other['status'], 'ready')
        self.assertNotEqual(self.digest, bridge.scope_digest('owner', '../account'))

    def test_encoder_window_metric_manifest_mismatch(self):
        for key, value in [('encoder_id', 'other'), ('window_hours', 24), ('target_metric', 'likes'), ('model_scope', 'personal'), ('data_scope', 'private'), ('platform', 'douyin'), ('dataset_license', ''), ('corpus_fingerprint', '')]:
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

    def test_training_history_change_does_not_invalidate_shared_model(self):
        for digest in ('b'*64, None, ''):
            self.config['_training_history_digest'] = digest
            self.assertTrue(bridge.availability('owner', 'account', self.config)['available'])

    def test_two_accounts_use_same_bundle_with_distinct_profiles(self):
        payloads = []
        def execute(argv, **kwargs):
            self.assertEqual(argv[argv.index('--bundle') + 1], str(self.bundle))
            payloads.append(json.loads(Path(argv[argv.index('--input') + 1]).read_text()))
            Path(argv[argv.index('--output') + 1]).write_text(json.dumps(self.successful_result()))
            return SimpleNamespace(returncode=0)
        with patch.object(bridge.subprocess, 'run', side_effect=execute):
            self.assertTrue(self.predict()['available'])
            other = [0., 1.] + [0.] * 510
            result = bridge.predict('other', 'account', self.config, self.candidates, bridge.MODEL_NAME, profile_vector=other)
            self.assertTrue(result['available'])
        self.assertNotEqual(payloads[0]['author_id'], payloads[1]['author_id'])
        self.assertNotEqual(payloads[0]['profile_vector'], payloads[1]['profile_vector'])
        self.assertTrue(all(set(p) == {'schema_version', 'author_id', 'profile_vector', 'platform', 'encoder_id', 'target_metric', 'window_hours', 'candidates'} for p in payloads))

    def test_missing_profile_never_executes(self):
        with patch.object(bridge.subprocess, 'run') as run:
            result = bridge.predict('owner', 'account', self.config, self.candidates, bridge.MODEL_NAME)
            self.assertEqual(result['status'], 'invalid_input')
            run.assert_not_called()

    def test_platform_required_and_old_personal_bundle_not_loaded(self):
        invalid = dict(self.config); invalid.pop('platform')
        self.assertFalse(bridge.availability('owner', 'account', invalid)['available'])
        (self.bundle / 'manifest.json').unlink()
        old = bridge.BUNDLES / self.digest; old.mkdir()
        (old / 'manifest.json').write_text(json.dumps(self.manifest))
        result = bridge.availability('owner', 'account', self.config)
        self.assertEqual(result['status'], 'not_trained')
        self.assertIn('无需为账号单独训练', result['message'])

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

    def test_real_shared_synthetic_bundle_hashes_match_and_web_refuses(self):
        # Real author architecture, trained only on synthetic fixtures. Never installed.
        actual = self.root / 'actual' / 'xiaohongshu' / 'views-72h'
        python = bridge.ROOT / 'runtime/skapp/venv/bin/python'
        program = "from pathlib import Path; import sys; from scripts import skapp_personal as p; from tests.test_skapp_personal import shared_dataset; p.train(shared_dataset(n=100,dim=512),Path(sys.argv[1]),epochs=1,k=3,synthetic=True)"
        completed = subprocess.run([str(python), '-c', program, str(actual)], cwd=bridge.ROOT, capture_output=True, text=True, timeout=180)
        self.assertEqual(completed.returncode, 0, completed.stderr[-3000:])
        manifest = bridge._read(actual / 'manifest.json')
        self.assertEqual(set(manifest['files']), {'weights.pt', 'references.json', 'corpus.json'})
        bridge._verify_artifacts(actual, manifest)
        from scripts.skapp_personal import corpus_fingerprint
        corpus = json.loads((actual / 'corpus.json').read_text())
        self.assertEqual(manifest['corpus_fingerprint'], corpus_fingerprint(corpus))
        with patch.object(bridge, 'BUNDLES', self.root / 'actual'):
            state = bridge.availability('owner', 'account', self.config)
            self.assertEqual(state['status'], 'trained_unvalidated')
            self.assertFalse(state['available'])
        self.assertTrue(manifest['synthetic'])
        self.assertFalse(manifest['ready_for_prediction'])

    def test_unvalidated_model_stays_unavailable(self):
        self.manifest['ready_for_prediction'] = False; self.write_manifest()
        self.assertEqual(bridge.availability('owner', 'account', self.config)['status'], 'trained_unvalidated')


if __name__ == '__main__':
    unittest.main()
