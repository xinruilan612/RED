import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend.api import create_app
from backend.provider import Config
from backend.store import Store
from backend.skapp_report import read_report


class SkappReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'report.json'
        self.patch = patch('backend.skapp_report.REPORT_PATH', self.path)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.data = {'status':'ready','scope':'public_benchmark','dataset':'icip','upstream_commit':'a'*40,
                     'metrics':{'MSE':2.0,'MAE':1.0,'SRC':0.4,'samples':2},
                     'predictions':[{'id':'one','actual':2.0,'predicted':3.0}],
                     'training':{'epochs':1,'device':'cpu','secret':'must not leak'}}

    def save(self):
        self.path.write_text(json.dumps(self.data))

    def test_missing_and_ready_report(self):
        self.assertEqual(read_report()['status'],'not_trained')
        self.save()
        report = read_report()
        self.assertEqual(report['status'],'ready')
        self.assertNotIn('secret',report['training'])
        self.assertEqual(report['predictions'][0]['actual'],2)

    def test_bad_numbers_scope_and_file_fail_closed_without_paths(self):
        self.save()
        for key,value in [('MSE',float('nan')),('MAE',-1),('SRC',1.1),('samples',True)]:
            old = self.data['metrics'][key]
            self.data['metrics'][key] = value
            self.save()
            self.assertEqual(read_report()['status'],'unavailable')
            self.data['metrics'][key] = old
        self.data['scope']='xiaohongshu'
        self.save()
        self.assertEqual(read_report()['status'],'unavailable')
        self.path.write_text('{ broken secret')
        self.assertNotIn('secret',json.dumps(read_report()))
        self.path.write_bytes(b'x'*4_000_001)
        self.assertEqual(read_report()['status'],'unavailable')

    def test_baseline_and_predictions_validate(self):
        self.data['baseline']={**self.data['metrics'],'name':'constant'}
        self.save()
        self.assertEqual(read_report()['baseline']['name'],'constant')
        self.data['baseline']['SRC']=None
        self.save()
        self.assertIsNone(read_report()['baseline']['SRC'])
        self.data['baseline']['samples']=3
        self.save()
        self.assertEqual(read_report()['status'],'unavailable')
        self.data.pop('baseline')
        self.data['predictions'][0]['actual']=float('inf')
        self.save()
        self.assertEqual(read_report()['status'],'unavailable')

    def test_http_requires_login_and_download_is_real_report(self):
        store=Store(str(Path(self.temp.name)/'app.sqlite'))
        with TestClient(create_app(store,Config(),origin='http://testserver',invite='')) as client:
            for endpoint in ('/api/skapp/report','/api/skapp/report/download'):
                self.assertEqual(client.get(endpoint).status_code,401)
            session=client.get('/api/session').json()
            registration=client.post('/api/auth/register',json={'username':'skapp_test','password':'Test-Skapp-2026'},headers={'Origin':'http://testserver','X-CSRF-Token':session['csrf']})
            self.assertEqual(registration.status_code,200,registration.text)
            self.assertEqual(client.get('/api/skapp/report').json()['status'],'not_trained')
            self.assertEqual(client.get('/api/skapp/report/download').status_code,404)
            self.save()
            download=client.get('/api/skapp/report/download')
            self.assertEqual(download.status_code,200)
            self.assertEqual(download.json()['metrics']['samples'],2)
            self.assertIn('attachment',download.headers['content-disposition'])
            self.assertNotIn('secret',download.text)
            asset=client.get('/skapp.js')
            self.assertEqual(asset.status_code,200)
            self.assertIn('text/javascript',asset.headers['content-type'])
