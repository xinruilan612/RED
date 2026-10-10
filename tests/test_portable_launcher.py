import io
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from scripts import portable_launcher as launcher
from backend import python_runtime

class PortableLauncherTests(unittest.TestCase):
    def test_user_paths_and_clean_environment(self):
        self.assertEqual(launcher.user_data_dir({'LOCALAPPDATA':'/user/local'},'win32'),Path('/user/local/Youji'))
        self.assertEqual(launcher.user_data_dir({'XDG_DATA_HOME':'/user/data'},'linux'),Path('/user/data/youji'))
        env=launcher.child_environment('/user/data',12345,{'deepseek_api_key':'provision-only','windtunnel_allow_live':False},inherited={'DATABASE_URL':'postgresql://production','DEEPSEEK_API_KEY':'wrong','HTTP_PROXY':'http://private','PATH':'/bin','PYTHONPATH':'/untrusted'})
        self.assertEqual(env['DATABASE_URL'],'/user/data/youji.sqlite')
        self.assertEqual(env['DEEPSEEK_API_KEY'],'provision-only')
        self.assertEqual(env['PUBLIC_ORIGIN'],'http://127.0.0.1:12345')
        self.assertEqual(env['YOUJI_IGNORE_PROJECT_ENV'],'1')
        import ssl
        self.assertTrue(Path(env['SSL_CERT_FILE']).is_file())
        self.assertGreater(ssl.create_default_context(cafile=env['SSL_CERT_FILE']).cert_store_stats()['x509_ca'], 0)
        self.assertNotIn('PYTHONPATH',env);self.assertNotIn('HTTP_PROXY',env)
    def test_provision_allowlist_and_no_shell(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'config.json'
            self.assertEqual(launcher.read_provision(p)['deepseek_api_key'],'')
            for raw in ('{"schema_version":1,"DATABASE_URL":"postgresql://production"}','{"schema_version":1,"deepseek_api_key":"x x"}','{"schema_version":1,"schema_version":1}','{"schema_version":1,"windtunnel_allow_live":"true"}'):
                p.write_text(raw)
                with self.assertRaises(ValueError):launcher.read_provision(p)
            p.write_text(json.dumps({'schema_version':1,'deepseek_api_key':'test-key','windtunnel_allow_live':True}))
            self.assertEqual(launcher.read_provision(p)['deepseek_api_key'],'test-key')
    def test_frozen_service_and_parser_commands(self):
        with patch.object(sys,'frozen',True,create=True):
            command=launcher.service_command('worker',12345,'/data','/marker')
            self.assertEqual(command[:3],[sys.executable,'--service','worker'])
            self.assertEqual(python_runtime.module_command('backend.document_parser'),[sys.executable,'--service','document-parser'])
            self.assertEqual(python_runtime.module_command('backend.word_parser'),[sys.executable,'--service','word-parser'])
        self.assertEqual(python_runtime.module_command('backend.word_parser'),[sys.executable,'-m','backend.word_parser'])
        with self.assertRaises(ValueError):python_runtime.module_command('os')
    def test_configuration_readers_skip_project_env(self):
        from backend import api,provider
        with patch.dict(os.environ,{'YOUJI_IGNORE_PROJECT_ENV':'1','DEEPSEEK_API_KEY':'provision-only'},clear=True),patch.object(Path,'read_text',side_effect=AssertionError('must not read project dotenv')):
            self.assertEqual(api.settings()['DEEPSEEK_API_KEY'],'provision-only')
            self.assertEqual(provider.load_config().api_key,'provision-only')
    def test_logs_redact_key(self):
        result=io.StringIO()
        launcher.log_stream(io.StringIO('failure private-key\n'),result,['private-key'],threading.Lock())
        self.assertNotIn('private-key',result.getvalue());self.assertIn('[REDACTED]',result.getvalue())
    def test_readiness_requires_this_worker_and_live_sqlite(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);db=root/'data.sqlite';marker=root/'marker'
            with sqlite3.connect(db) as c:c.execute('CREATE TABLE runtime_workers(id TEXT,heartbeat DOUBLE)');c.execute('INSERT INTO runtime_workers VALUES(?,?)',('worker',time.time()))
            marker.write_text('{"worker_id":"worker"}')
            response=io.BytesIO(b'{"status":"ok","database":"sqlite"}')
            with patch.object(launcher.urllib.request,'build_opener') as opener:
                opener.return_value.open.return_value=response
                self.assertTrue(launcher.ready('http://127.0.0.1:12345',db,marker))
            marker.write_text('{"worker_id":"other"}')
            with patch.object(launcher.urllib.request,'build_opener') as opener:
                opener.return_value.open.return_value=io.BytesIO(b'{"status":"ok","database":"sqlite"}')
                self.assertFalse(launcher.ready('http://127.0.0.1:12345',db,marker))
    def test_real_bundled_parser_dispatch_and_knowledge_contract(self):
        from tests.test_knowledge_sources import text_pdf, text_docx
        from backend.knowledge import parse_file
        for service, suffix, content in [('document-parser', 'pdf', text_pdf()), ('word-parser', 'docx', text_docx())]:
            process=subprocess.run([sys.executable,str(Path(launcher.__file__).resolve()),'--service',service],input=content,capture_output=True,timeout=15)
            self.assertEqual(process.returncode,0,process.stderr.decode(errors='replace'))
            packet=json.loads(process.stdout)
            key='pages' if suffix=='pdf' else 'paragraphs'
            self.assertEqual(packet[key],[list(row) for row in parse_file('test.'+suffix,content)])

    def run_command(self,data,*args):
        return [sys.executable,str(Path(launcher.__file__).resolve()),'--data-dir',str(data),*args]
    def test_real_sqlite_check_restart_and_children_cleanup(self):
        with tempfile.TemporaryDirectory(prefix='youji-portable-test-') as d:
            data=Path(d)/'user';ready=Path(d)/'ready.json'
            for attempt in range(2):
                result=subprocess.run(self.run_command(data,'--check','--ready-file',str(ready)),capture_output=True,text=True,timeout=60)
                self.assertEqual(result.returncode,0,result.stderr)
                packet=json.loads(ready.read_text());self.assertTrue(packet['ready'])
                self.assertTrue(packet['origin'].startswith('http://127.0.0.1:'))
                with sqlite3.connect(data/'youji.sqlite') as db:
                    db.execute('CREATE TABLE IF NOT EXISTS launcher_test_sentinel(value TEXT)')
                    if attempt==0:db.execute("INSERT INTO launcher_test_sentinel VALUES('preserved')")
                    else:self.assertEqual(db.execute('SELECT value FROM launcher_test_sentinel').fetchone()[0],'preserved')
                for key in ('api_pid','worker_pid'):
                    with self.assertRaises(OSError):os.kill(packet[key],0)
            self.assertFalse(list(data.glob('worker-ready-*')))
    def test_worker_failure_stops_peer_and_parent(self):
        with tempfile.TemporaryDirectory(prefix='youji-portable-failure-') as d:
            data=Path(d)/'user';ready=Path(d)/'ready.json'
            process=subprocess.Popen(self.run_command(data,'--no-browser','--ready-file',str(ready)),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            try:
                deadline=time.monotonic()+45
                while not ready.exists() and process.poll() is None and time.monotonic()<deadline:time.sleep(.1)
                self.assertTrue(ready.exists())
                packet=json.loads(ready.read_text());os.kill(packet['worker_pid'],signal.SIGTERM)
                out,error=process.communicate(timeout=15)
                self.assertEqual(process.returncode,1)
                with self.assertRaises(OSError):os.kill(packet['api_pid'],0)
                self.assertIn('两个服务已停止',error)
            finally:
                if process.poll() is None:process.terminate();process.communicate(timeout=15)

if __name__=='__main__':unittest.main()
