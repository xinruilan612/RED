"""Connector tokens are retained server-side, absent from API/state/model context."""
import json
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend.api import create_app
from backend.provider import Config
from backend.store import Store
from backend.public_topics import public_response

class PublicRedactionTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.app=create_app(Store(Path(self.folder.name)/'db'),Config(),origin='http://testserver',invite='')
        self.client=TestClient(self.app);self.addCleanup(self.client.close)
        csrf=self.client.get('/api/session').json()['csrf']
        self.headers={'Origin':'http://testserver','X-CSRF-Token':csrf}
        response=self.client.post('/api/auth/register',json={'username':'redaction_user','password':'TestingPass123'},headers=self.headers)
        self.headers['X-CSRF-Token']=response.json()['csrf']
        self.owner=self.app.state.auth.session(self.client.cookies.get('youji_session'))['owner']
        self.ops=self.app.state.service.operations;state=self.ops.read(self.owner);self.account=state['accounts'][0]
        self.ops.command(self.owner,dict(action='public_topics_update',payload={'account_id':self.account['id'],'samples':[{'id':'fixture123','title':'fixture','xsec_token':'fixture-secret-only','nested':{'xsecToken':'fixture-secret-only'}}]},version=state['version'],key=str(uuid4())),internal=True)
    def check_clean(self,response):
        self.assertEqual(response.status_code,200,response.text)
        self.assertNotIn('fixture-secret-only',response.text);self.assertNotIn('xsec_token',response.text);self.assertNotIn('xsecToken',response.text)
    def test_get_and_command_redacted_but_server_preserved(self):
        self.check_clean(self.client.get('/api/operations'))
        state=self.ops.read(self.owner)
        data=dict(action='save_account',payload={k:self.account[k] for k in ('id','name','platform','profile')},version=state['version'],key=str(uuid4()))
        self.check_clean(self.client.post('/api/operations',json=data,headers=self.headers))
        saved=self.ops.read(self.owner)['public_topic_samples'][self.account['id']][0]
        self.assertEqual(saved['xsec_token'],'fixture-secret-only')
    def test_nested_agent_and_review_responses_redacted(self):
        service=self.app.state.service
        response={'operations':self.ops.read(self.owner)}
        with patch.object(service.operations_planner,'generate',return_value=response):
            self.check_clean(self.client.post('/api/operations/agent-plan',json={},headers=self.headers))
        with patch.object(service.analytics_review,'generate',return_value=response):
            self.check_clean(self.client.post('/api/operations/ai-review',json={},headers=self.headers))
    def test_source_tokens_not_in_llm_operations_context(self):
        context=self.ops.context(self.owner,{'account_id':self.account['id']},'live')
        self.assertNotIn('fixture-secret-only',json.dumps(context));self.assertNotIn('public_topic_samples',context)
    def test_public_serializer_does_not_mutate_input(self):
        original={'nested':[{'xsec_token':'fixture','title':'retain'}]}
        self.assertEqual(public_response(original),{'nested':[{'title':'retain'}]});self.assertIn('xsec_token',original['nested'][0])
