"""Subprocess and session boundaries without visiting a platform."""
import json
import os
import signal
import sys
import time
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from backend.creator_reader import collect_creator, run_reader, _reader_family, _signal_family
from backend.xhs_local import LocalXHS
from scripts.xhs_creator_reader import bootstrap_cookies, private_json, ReaderStopped


class CreatorReaderTests(unittest.TestCase):
    def test_unbound_or_invalid_identity_never_launches(self):
        run = Mock()
        self.assertEqual(collect_creator('../other', run)['error'], 'CREATOR_IDENTITY_INVALID')
        with tempfile.TemporaryDirectory() as root, patch('backend.creator_reader.ROOT', Path(root)):
            self.assertEqual(collect_creator('a'*24, run)['error'], 'CREATOR_NOT_BOUND')
        run.assert_not_called()

    def configured(self, root):
        path = Path(root)
        binding = path/'runtime/xhs-local/creator'/('a'*24)/'binding.json'
        private_json(binding, {'source_id': 'a'*24, 'creator_account_id': '123'})
        executable = path/'runtime/mediacrawler/.venv/bin/python'
        executable.parent.mkdir(parents=True)
        executable.touch()

    def test_fixed_command_and_identity_guard(self):
        with tempfile.TemporaryDirectory() as root, patch('backend.creator_reader.ROOT', Path(root)):
            self.configured(root)
            run = Mock(return_value=SimpleNamespace(returncode=0, stdout=json.dumps({'source_id':'a'*24,'status':'synced'}).encode()))
            self.assertEqual(collect_creator('a'*24, run)['status'], 'synced')
            command = run.call_args.args[0]
            self.assertEqual(command[-2:], ['--source-id','a'*24])
            self.assertNotIn('shell', run.call_args.kwargs)
            run.return_value.stdout = b'{"source_id":"different","status":"synced"}'
            self.assertEqual(collect_creator('a'*24, run)['error'], 'CREATOR_READER_FAILED')
            run.side_effect = subprocess.TimeoutExpired('private-browser-command', 1, output=b'private')
            result = collect_creator('a'*24, run)
            self.assertEqual(result['status'], 'failed')
            self.assertNotIn('private', json.dumps(result))

    def test_cookie_bootstrap_keeps_only_platform_fields_and_private_mode(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)/'session.json'
            private_json(path, [
                {'domain':'.xiaohongshu.com','name':'session','value':'secret','path':'/','sameSite':'Lax','unrelated':'drop'},
                {'domain':'.evilxiaohongshu.com','name':'session','value':'other'},
            ])
            result = bootstrap_cookies(path)
            self.assertEqual(len(result), 1)
            self.assertNotIn('unrelated', result[0])
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            private_json(path, {'version': 2, 'seed': 'not_exported', 'cookies': result})
            self.assertEqual(bootstrap_cookies(path), result)
            private_json(path, [])
            with self.assertRaises(ReaderStopped): bootstrap_cookies(path)

    def test_creator_failure_does_not_drop_comments_and_rechecks_identity(self):
        client = LocalXHS()
        client.identity = Mock(return_value={'id':'a'*24})
        client.request = Mock(return_value={'data':{'feeds':[]}})
        with patch('backend.creator_reader.collect_creator', return_value={'status':'failed','error':'CREATOR_LOGIN_REQUIRED'}):
            result = client.collect('a'*24)
        self.assertEqual(result['notes'], [])
        self.assertEqual(result['creator_metrics']['error'], 'CREATOR_LOGIN_REQUIRED')
        self.assertEqual(client.identity.call_count, 3)

    def test_descendant_inventory_excludes_other_browser_groups(self):
        rows={10:(1,10,'a'),11:(10,10,'b'),12:(11,12,'c'),13:(12,12,'d'),20:(1,20,'e')}
        self.assertEqual(set(_reader_family(10,rows)),{10,11,12,13})

    def test_reused_pid_or_foreign_group_is_not_signalled_as_owned_group(self):
        family={10:(1,10,'old-start'),11:(10,99,'child-start')}
        current={10:(1,10,'new-start'),11:(1,99,'child-start')}
        with patch('backend.creator_reader._process_snapshot',return_value=current), \
             patch('backend.creator_reader.os.killpg') as groups, \
             patch('backend.creator_reader.os.kill') as individual:
            _signal_family(family,signal.SIGTERM)
        groups.assert_not_called()
        individual.assert_called_once_with(11,signal.SIGTERM)

    def test_timeout_kills_detached_descendant_but_keeps_unrelated_process(self):
        # Real local processes, no browser/network/cookies. Child ignores TERM
        # and disconnects output; parent exit must not skip the KILL fallback.
        child_code='import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(60)'
        parent_code=("import subprocess,sys,time;"
          "p=subprocess.Popen([sys.executable,'-c',"+repr(child_code)+"],start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);"
          "print(p.pid,flush=True);time.sleep(60)")
        unrelated=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],start_new_session=True)
        child=None
        try:
            with self.assertRaises(subprocess.TimeoutExpired) as caught:
                run_reader([sys.executable,'-c',parent_code],timeout=.5)
            child=int(caught.exception.output.strip())
            deadline=time.monotonic()+3
            running=True
            while time.monotonic()<deadline:
                result=subprocess.run(['/bin/ps','-p',str(child),'-o','stat='],capture_output=True,text=True)
                running=result.returncode==0 and bool(result.stdout.strip()) and not result.stdout.strip().startswith('Z')
                if not running:break
                time.sleep(.05)
            self.assertFalse(running,'Detached descendant survived timeout cleanup')
            self.assertIsNone(unrelated.poll(),'Unrelated process was killed')
        finally:
            if child:
                try:os.killpg(child,signal.SIGKILL)
                except ProcessLookupError:pass
            unrelated.kill();unrelated.wait(timeout=3)


if __name__ == '__main__':
    unittest.main()
