import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import venv

from scripts import local_dev
from backend.api import settings


class LocalDevTests(unittest.TestCase):
    def test_start_probe_allows_restart_after_closed_tcp_connection(self):
        from unittest.mock import MagicMock
        probe=MagicMock();api=MagicMock();api.poll.return_value=None;worker=MagicMock();worker.poll.return_value=None
        with patch.object(local_dev.socket,'socket') as sock, patch.object(local_dev.subprocess,'Popen',side_effect=[api,worker]), patch.object(local_dev.time,'sleep',side_effect=KeyboardInterrupt):
            sock.return_value.__enter__.return_value=probe
            local_dev.serve({'PUBLIC_ORIGIN':'http://127.0.0.1:8766'})
        probe.setsockopt.assert_called_once_with(local_dev.socket.SOL_SOCKET,local_dev.socket.SO_REUSEADDR,1)

    def test_platform_paths(self):
        root = Path('/project')
        self.assertEqual(local_dev.python_path(root, True), root/'runtime/venv/Scripts/python.exe')
        self.assertEqual(local_dev.python_path(root, False), root/'runtime/venv/bin/python')

    def test_existing_project_environments_are_preferred_without_modifying_path(self):
        for windows, suffix in ((True, 'Scripts/python.exe'), (False, 'bin/python')):
            with self.subTest(windows=windows), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                standard = root/'.venv'/suffix
                standard.parent.mkdir(parents=True)
                standard.touch()
                self.assertEqual(local_dev.python_path(root, windows), standard)
                established = root/'runtime/venv'/suffix
                established.parent.mkdir(parents=True)
                established.touch()
                self.assertEqual(local_dev.python_path(root, windows), established)

    def test_existing_dot_venv_does_not_reexec_itself_forever(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            interpreter = root/'.venv'/('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
            interpreter.parent.mkdir(parents=True)
            interpreter.touch()
            with patch.object(local_dev, 'ROOT', root), patch.object(local_dev, 'python_path', return_value=interpreter), \
                    patch.object(local_dev.os, 'chdir'), patch.object(local_dev.sys, 'prefix', str(root/'.venv')), \
                    patch.object(local_dev.sys, 'argv', ['local_dev.py', 'doctor']), \
                    patch.object(local_dev, 'doctor', return_value={}) as doctor, patch.object(local_dev.subprocess, 'call') as restart:
                self.assertEqual(local_dev.main(), 0)
            doctor.assert_called_once()
            restart.assert_not_called()

    def test_contract_load_does_not_depend_on_system_encoding(self):
        import runpy
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
            with patch.object(local_dev.venv, 'EnvBuilder') as builder, patch.object(local_dev.subprocess, 'run') as run:
                local_dev.setup(root)
            self.assertEqual((root/'.env').read_text(), 'PRIVATE=keep')
            builder.return_value.create.assert_called_once_with(root/'runtime/venv')
            self.assertTrue(run.call_args.kwargs['check'])
            self.assertEqual(run.call_args.kwargs['cwd'], root)
            self.assertEqual(run.call_args.kwargs['env']['PYTHONUTF8'], '1')
            self.assertEqual(run.call_args.kwargs['env']['PYTHONIOENCODING'], 'utf-8')
            self.assertTrue((root/'runtime').is_dir())

    def test_setup_copies_template_only_after_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'.env.example').write_text('EXAMPLE=yes', encoding='utf-8')
            with patch.object(local_dev.venv, 'EnvBuilder'), patch.object(local_dev.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'pip')):
                with self.assertRaises(subprocess.CalledProcessError):
                    local_dev.setup(root)
            self.assertFalse((root/'.env').exists())
            with patch.object(local_dev.venv, 'EnvBuilder'), patch.object(local_dev.subprocess, 'run'):
                local_dev.setup(root)
            self.assertEqual((root/'.env').read_text(), 'EXAMPLE=yes')

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

    def test_runtime_is_created_before_child_launch_and_unicode_environment_is_explicit(self):
        with tempfile.TemporaryDirectory(prefix='启动器 路径 ') as directory:
            root = Path(directory)
            children = [Mock(), Mock()]
            for child in children:
                child.poll.return_value = None
            def launch(*args, **kwargs):
                self.assertTrue((root/'runtime').is_dir())
                self.assertEqual(kwargs['cwd'], root)
                self.assertEqual(kwargs['env']['PYTHONUTF8'], '1')
                self.assertEqual(kwargs['env']['PYTHONIOENCODING'], 'utf-8')
                return children.pop(0)
            with patch.object(local_dev, 'ROOT', root), patch.object(local_dev.socket, 'socket'), \
                    patch.object(local_dev.subprocess, 'Popen', side_effect=launch), \
                    patch.object(local_dev.time, 'sleep', side_effect=KeyboardInterrupt):
                local_dev.serve({})

    def test_bootstrap_reexec_preserves_arguments_cwd_and_utf8_without_reading_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            interpreter = root/'runtime/venv'/('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
            interpreter.parent.mkdir(parents=True)
            interpreter.touch()
            with patch.object(local_dev, 'ROOT', root), patch.object(local_dev, 'python_path', return_value=interpreter), \
                    patch.object(local_dev.os, 'chdir'), patch.object(local_dev.sys, 'prefix', 'different-prefix'), \
                    patch.object(local_dev.sys, 'argv', ['local_dev.py', 'doctor']), \
                    patch.object(local_dev, 'doctor') as doctor, patch.object(local_dev.subprocess, 'call', return_value=7) as restart:
                self.assertEqual(local_dev.main(), 7)
            doctor.assert_not_called()
            self.assertEqual(restart.call_args.args[0][0], str(interpreter))
            self.assertEqual(restart.call_args.args[0][-1], 'doctor')
            self.assertEqual(restart.call_args.kwargs['cwd'], root)
            self.assertEqual(restart.call_args.kwargs['env']['PYTHONIOENCODING'], 'utf-8')

    def test_bootstrap_rejects_old_python_before_loading_application_or_database(self):
        with patch.object(local_dev.os, 'chdir'), patch.object(local_dev.sys, 'version_info', (3, 11)), \
                patch.object(local_dev.sys, 'argv', ['local_dev.py', 'doctor']), patch.object(local_dev, 'doctor') as doctor, \
                patch('sys.stderr', new_callable=io.StringIO) as error:
            self.assertEqual(local_dev.main(), 1)
        doctor.assert_not_called()
        self.assertIn('Python 3.12', error.getvalue())

    def test_unix_entrypoints_are_lf_only_and_share_one_launcher(self):
        for filename in ('start-unix.sh', 'start-macos.command'):
            raw = (local_dev.ROOT/filename).read_bytes()
            self.assertNotIn(b'\r', raw)
            self.assertTrue(raw.startswith(b'#!/bin/sh\n'))
        self.assertIn('start-unix.sh', (local_dev.ROOT/'start-macos.command').read_text(encoding='utf-8'))

    def launcher_project(self, directory):
        root = Path(directory)/'项目 含空格'
        (root/'scripts').mkdir(parents=True)
        for filename in ('start-unix.sh', 'start-macos.command', 'start-windows.cmd'):
            shutil.copyfile(local_dev.ROOT/filename, root/filename)
        shutil.copyfile(local_dev.ROOT/'scripts/local_dev.py', root/'scripts/local_dev.py')
        (root/'.env').write_text('UNCHANGED=中文测试配置\n', encoding='utf-8')
        return root

    def assert_unix_entrypoints_from_external_cwd(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.launcher_project(directory)
            interpreter = root/'.venv/bin/python'
            interpreter.parent.mkdir(parents=True)
            interpreter.write_text(f'#!/bin/sh\nprintf "PROJECT_VENV_SELECTED\\n" >&2\nexec "{sys.executable}" "$@"\n', encoding='utf-8')
            interpreter.chmod(0o755)
            for entry in ('start-unix.sh', 'start-macos.command'):
                with self.subTest(entry=entry):
                    result = subprocess.run(['/bin/sh', str(root/entry), '--help'], cwd=directory, capture_output=True, text=True, encoding='utf-8', timeout=15)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn('PROJECT_VENV_SELECTED', result.stderr)
                    self.assertIn('setup,doctor,start', result.stdout)
            self.assertEqual((root/'.env').read_text(encoding='utf-8'), 'UNCHANGED=中文测试配置\n')
            self.assertFalse((root/'runtime').exists())

    def assert_windows_entrypoint_from_external_cwd(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.launcher_project(directory)
            venv.EnvBuilder(with_pip=False).create(root/'.venv')
            result = subprocess.run(f'cmd.exe /d /c ""{root / "start-windows.cmd"}" --help"', cwd=directory,
                                    env={**os.environ, 'RED_NO_PAUSE': '1'}, stdin=subprocess.DEVNULL,
                                    capture_output=True, text=True, encoding='utf-8', timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('setup,doctor,start', result.stdout)
            self.assertEqual((root/'.env').read_text(encoding='utf-8'), 'UNCHANGED=中文测试配置\n')
            self.assertFalse((root/'runtime').exists())

    def test_native_entrypoints_run_from_unicode_space_path_outside_repo(self):
        # Each OS executes its real shell entrypoint. POSIX also exercises the
        # shared .command script; this is not a claim of macOS hardware testing.
        if os.name == 'nt':
            self.assert_windows_entrypoint_from_external_cwd()
        else:
            self.assert_unix_entrypoints_from_external_cwd()

    def test_ctrl_c_stops_both_children(self):
        children = [Mock(), Mock()]
        for child in children:
            child.poll.return_value = None
        with patch.object(local_dev.socket, 'socket'), patch.object(local_dev.subprocess, 'Popen', side_effect=children), patch.object(local_dev.time, 'sleep', side_effect=KeyboardInterrupt):
            local_dev.serve({})
        for child in children:
            child.terminate.assert_called_once()
            child.wait.assert_called_once()
