import io
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts import local_dev
from backend.api import settings


class LocalDevTests(unittest.TestCase):
    def test_platform_paths(self):
        root = Path('/project')
        self.assertEqual(local_dev.python_path(root, True), root/'runtime/venv/Scripts/python.exe')
        self.assertEqual(local_dev.python_path(root, False), root/'runtime/venv/bin/python')

    def test_contract_load_does_not_depend_on_system_encoding(self):
        original = Path.read_text
        def windows_read(path, *args, **kwargs):
            kwargs.setdefault('encoding', 'ascii')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'read_text', windows_read):
            namespace = runpy.run_path(str(local_dev.ROOT/'backend/contracts.py'))
        self.assertIn('parameters', namespace['CONTRACT'])

    def test_setup_preserves_existing_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'.env').write_text('PRIVATE=keep', encoding='utf-8')
            virtualenv = Mock()
            with patch.dict('sys.modules', {'venv': virtualenv}), patch.object(local_dev.subprocess, 'run') as run:
                local_dev.setup(root)
            self.assertEqual((root/'.env').read_text(), 'PRIVATE=keep')
            virtualenv.EnvBuilder.assert_called_once_with(with_pip=True)
            virtualenv.EnvBuilder.return_value.create.assert_called_once_with(root/'runtime/venv')
            self.assertEqual(run.call_args.kwargs, {'check': True, 'cwd': root})

    def test_setup_copies_template_only_after_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'.env.example').write_text('EXAMPLE=yes', encoding='utf-8')
            with patch.dict('sys.modules', {'venv': Mock()}), patch.object(local_dev.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'pip')):
                with self.assertRaises(subprocess.CalledProcessError):
                    local_dev.setup(root)
            self.assertFalse((root/'.env').exists())
            with patch.dict('sys.modules', {'venv': Mock()}), patch.object(local_dev.subprocess, 'run'):
                local_dev.setup(root)
            self.assertEqual((root/'.env').read_text(), 'EXAMPLE=yes')

    def test_import_without_venv_is_supported(self):
        with patch.dict('sys.modules', {'venv': None}):
            namespace = runpy.run_path(str(local_dev.ROOT/'scripts/local_dev.py'))
        self.assertTrue(callable(namespace['setup']))

    def test_setup_without_venv_explains_full_python_requirement(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict('sys.modules', {'venv': None}), patch.object(local_dev.subprocess, 'run') as run:
                with self.assertRaisesRegex(RuntimeError, 'full Python 3.12.*with venv'):
                    local_dev.setup(root)
            run.assert_not_called()
            self.assertFalse((root/'runtime').exists())
            self.assertFalse((root/'.env').exists())

    def test_existing_environment_does_not_require_venv_module(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            interpreter = local_dev.python_path(root)
            interpreter.parent.mkdir(parents=True)
            interpreter.touch()
            (root/'.env').write_text('PRIVATE=keep', encoding='utf-8')
            with patch.dict('sys.modules', {'venv': None}), patch.object(local_dev.subprocess, 'run') as run:
                local_dev.setup(root)
            self.assertEqual(run.call_args.args[0][0], str(interpreter))
            self.assertEqual((root/'.env').read_text(encoding='utf-8'), 'PRIVATE=keep')

    def test_local_origin_only(self):
        self.assertEqual(local_dev.endpoint({'PUBLIC_ORIGIN':'http://localhost:9876/'}), ('127.0.0.1', 9876, 'http://localhost:9876'))
        for origin in ['https://example.com', 'http://user:secret@localhost', 'http://localhost/path', 'http://localhost:bad']:
            with self.subTest(origin=origin), self.assertRaises(RuntimeError):
                local_dev.endpoint({'PUBLIC_ORIGIN':origin})

    def test_utf8_bom_config_and_environment_precedence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'.env'
            path.write_text('REGISTRATION_INVITE=中文邀请\nPUBLIC_ORIGIN=http://localhost:8765', encoding='utf-8-sig')
            with patch('backend.api.Path') as paths, patch.dict('os.environ', {'PUBLIC_ORIGIN':'http://127.0.0.1:8765'}, clear=True):
                paths.return_value.resolve.return_value.parents.__getitem__.return_value = Path(directory)
                env = settings()
            self.assertEqual(env['REGISTRATION_INVITE'], '中文邀请')
            self.assertEqual(env['PUBLIC_ORIGIN'], 'http://127.0.0.1:8765')

    def test_doctor_masks_database_credentials(self):
        with patch('backend.api.settings', return_value={'DATABASE_URL':'postgresql://private:secret@localhost/db'}), patch('backend.database.connect', side_effect=ValueError('private:secret')), patch('sys.stdout', new_callable=io.StringIO):
            with self.assertRaises(RuntimeError) as error:
                local_dev.doctor()
        self.assertNotIn('secret', str(error.exception))
        self.assertNotIn('private', str(error.exception))

    def test_start_failure_stops_both_children(self):
        api, worker = Mock(), Mock()
        api.poll.return_value = 1
        worker.poll.return_value = None
        with patch.object(local_dev.socket, 'socket'), patch.object(local_dev.subprocess, 'Popen', side_effect=[api, worker]) as launch:
            with self.assertRaises(RuntimeError):
                local_dev.serve({})
        worker.terminate.assert_called_once()
        api.wait.assert_called_once()
        worker.wait.assert_called_once()
        self.assertEqual(launch.call_args_list[1].args[0][-1], 'backend.worker')

    def test_ctrl_c_stops_both_children(self):
        children = [Mock(), Mock()]
        for child in children:
            child.poll.return_value = None
        with patch.object(local_dev.socket, 'socket'), patch.object(local_dev.subprocess, 'Popen', side_effect=children), patch.object(local_dev.time, 'sleep', side_effect=KeyboardInterrupt):
            local_dev.serve({})
        for child in children:
            child.terminate.assert_called_once()
            child.wait.assert_called_once()
