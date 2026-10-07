"""Offline command/evidence gates: never download or train during site tests."""
import json
from pathlib import Path
import tempfile
import unittest
from scripts import skapp_experiment as skapp


class SkappExperimentTests(unittest.TestCase):
    def test_constant_baseline_has_undefined_rank_correlation(self):
        result = skapp.constant_baseline([1, 3, 5], [0, 2])
        self.assertIsNone(result['SRC'])
        self.assertAlmostEqual(result['MSE'], 20 / 3)
        self.assertEqual(result['MAE'], 2)
        self.assertEqual(result['samples'], 3)
        self.assertIn('"SRC": null', json.dumps(result))

    def test_constant_baseline_rejects_empty_test_set(self):
        with self.assertRaises(ValueError):
            skapp.constant_baseline([], [1, 2])

    def test_pinned_vendor_files_unchanged(self):
        skapp.verify_vendor()

    def test_cpu_is_default_and_separate_python_is_explicit(self):
        with tempfile.TemporaryDirectory() as folder:
            args = skapp.parser().parse_args(['train','--python','/tmp/skapp/python', '--dataset-path',folder,
                                             '--output-dir',folder+'/new'])
            cmd = skapp.command(args)
            self.assertEqual(cmd[0], '/tmp/skapp/python')
            self.assertEqual(cmd[cmd.index('--device')+1], 'cpu')
            self.assertEqual(cmd[cmd.index('--epochs')+1], '60')
            self.assertNotIn('--simulate', cmd)

    def test_existing_training_output_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            args = skapp.parser().parse_args(['train','--python','/tmp/skapp/python','--dataset-path',folder,'--output-dir',folder])
            with self.assertRaises(FileExistsError):
                skapp.command(args)

    def test_live_environment_is_rejected(self):
        args = skapp.parser().parse_args(['download','--python',str(skapp.ROOT/'runtime/venv/bin/python')])
        with self.assertRaisesRegex(ValueError, 'separate SKAPP'):
            skapp.command(args)

    def test_download_can_use_verified_local_archive(self):
        args = skapp.parser().parse_args(['download','--python','/tmp/skapp/python','--archive','/tmp/data.zip'])
        self.assertEqual(skapp.command(args)[-2:], ['--archive','/tmp/data.zip'])

    def test_incomplete_evaluation_cannot_publish(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            (path/'result.json').write_text(json.dumps({'status':'failed'}))
            args = skapp.parser().parse_args(['publish','--evaluation-dir',folder,'--output',folder+'/site.json'])
            with self.assertRaisesRegex(ValueError,'not complete'):
                skapp.publish(args)
            self.assertFalse((path/'site.json').exists())

    def test_publish_refuses_selecting_best_test_seed(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            for name,value in [('result.json',{'status':'complete'}),('progress.json',{'status':'complete'}),('manifest.json',{'seeds':[12,13]})]:
                (path/name).write_text(json.dumps(value))
            args = skapp.parser().parse_args(['publish','--evaluation-dir',folder,'--output',folder+'/site.json'])
            with self.assertRaisesRegex(ValueError,'predeclared seed'):
                skapp.publish(args)
            self.assertFalse((path/'site.json').exists())

    def test_publish_rejects_modified_evaluation_manifest(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            for name,value in [('result.json',{'status':'complete'}),('progress.json',{'status':'complete'}),
                               ('manifest.json',{'seeds':[12],'runs':[{'seed':12,'manifest':'seed.json','sha256':'invalid'}]}),('seed.json',{})]:
                (path/name).write_text(json.dumps(value))
            args = skapp.parser().parse_args(['publish','--evaluation-dir',folder,'--output',folder+'/site.json'])
            with self.assertRaisesRegex(ValueError,'manifest changed'):
                skapp.publish(args)
