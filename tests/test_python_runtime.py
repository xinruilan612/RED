"""Cross-platform optional subprocess interpreter selection, no actual inference."""
import importlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from backend import python_runtime, topic_encoder, skapp_personal
from scripts import skapp_experiment

class PythonRuntimeTests(unittest.TestCase):
    def test_native_layouts_do_not_depend_on_installed_alternative(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            unix=root/'bin/python';unix.parent.mkdir();unix.touch()
            self.assertEqual(python_runtime.venv_python(root,windows=False),unix)
            self.assertEqual(python_runtime.venv_python(root,windows=True),root/'Scripts/python.exe')
            self.assertFalse(python_runtime.venv_python(root,windows=True).exists())
    def test_both_bridges_select_windows_executable_at_import(self):
        try:
            with patch.object(python_runtime,'os',SimpleNamespace(name='nt')):
                importlib.reload(topic_encoder);importlib.reload(skapp_personal)
                expected=topic_encoder.ROOT/'runtime/skapp/venv/Scripts/python.exe'
                self.assertEqual(topic_encoder.PYTHON,expected)
                self.assertEqual(skapp_personal.PYTHON,expected)
        finally:
            importlib.reload(topic_encoder);importlib.reload(skapp_personal)
    def test_encoder_runs_fixed_windows_path_without_shell_or_fallback(self):
        path=topic_encoder.ROOT/'runtime/skapp/venv/Scripts/python.exe'
        result={'model':topic_encoder.MODEL_NAME,'dimension':512,'text_vectors':[[1.]+[0.]*511],'image_vectors':[]}
        with patch.object(topic_encoder,'PYTHON',path),patch.object(topic_encoder,'availability',return_value={'ready':True}),patch.object(topic_encoder.subprocess,'run',return_value=subprocess.CompletedProcess([],0,json.dumps(result),'')) as run:
            self.assertEqual(topic_encoder.encode(['中文']),result)
            self.assertEqual(run.call_args.args[0][0],str(path))
            self.assertNotIn('shell',run.call_args.kwargs)
        with patch.object(topic_encoder,'PYTHON',path),patch.object(topic_encoder,'availability',return_value={'ready':True}),patch.object(topic_encoder.subprocess,'run',side_effect=OSError('missing runtime')) as run:
            with self.assertRaises(topic_encoder.TopicEncoderError):topic_encoder.encode(['中文'])
            self.assertEqual(run.call_count,1)
    def test_website_environment_guard_recognizes_both_layouts(self):
        for suffix in ('bin/python','Scripts/python.exe'):
            interpreter=skapp_experiment.ROOT/'runtime/venv'/suffix
            self.assertTrue(python_runtime.is_venv_python(interpreter,skapp_experiment.ROOT/'runtime/venv'))
            with patch.object(skapp_experiment,'verify_vendor'):
                with self.assertRaisesRegex(ValueError,'separate SKAPP'):
                    skapp_experiment.command(SimpleNamespace(python=str(interpreter)))
        self.assertFalse(python_runtime.is_venv_python(skapp_experiment.ROOT/'runtime/skapp/venv/Scripts/python.exe',skapp_experiment.ROOT/'runtime/venv'))

if __name__=='__main__':unittest.main()
