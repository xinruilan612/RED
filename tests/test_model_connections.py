"""BYOK encryption, tenant isolation, frozen routing and transport contracts (offline)."""
import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from backend.contracts import DomainError
from backend.credentials import CredentialVault
from backend.private_files import is_private_file
from backend.model_connections import ModelConnections,PROVIDERS,base_url
from backend.provider import Config,ConnectedModel,connected_request
from backend.service import Service
from backend.store import Store
from backend.workflow import Run
from test_live_provider import FixtureModel


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name)/'test.sqlite')
        self.service=Service(self.store,Config())
        self.models=self.service.models
        self.models.vault=CredentialVault(self.store,environ={})

    def save(self,owner='alice',**changes):
        data=dict(provider='qwen',model='qwen-example',api_key='secret-never-public',rate_usd_per_million=2,run_budget_usd=1,day_budget_usd=5)
        data.update(changes);return self.models.save(owner,data)

    def test_encryption_restart_isolation_and_no_secret_in_public(self):
        item=self.save();self.models.select('alice',{'connection_id':item['id']})
        with self.store.connect() as db:
            ciphertext=db.execute('SELECT secret FROM model_connections').fetchone()[0]
        self.assertNotIn('secret-never-public',ciphertext)
        self.assertEqual(CredentialVault(self.store,environ={}).decrypt(ciphertext),'secret-never-public')
        self.assertTrue(is_private_file(Path(self.temp.name)/'credentials.key'))
        self.assertNotIn('secret-never-public',json.dumps(self.models.public('alice')))
        self.assertEqual(self.models.public('bob')['connections'],[])
        with self.assertRaises(DomainError):self.models.select('bob',{'connection_id':item['id']})
        with self.assertRaises(DomainError):self.models.adapter(self.models.route('alice'),'bob')
        self.assertEqual(self.models.effective_public('alice')['billing_source'],'user')

    def test_public_deployment_requires_master_key_and_bad_keys_safe(self):
        from cryptography.fernet import Fernet
        with self.assertRaises(DomainError):CredentialVault(self.store,{'PUBLIC_ORIGIN':'https://example.com'}).encrypt('secret')
        vault=CredentialVault(self.store,{'PUBLIC_ORIGIN':'https://example.com','MODEL_CREDENTIAL_KEY':Fernet.generate_key().decode()})
        self.assertEqual(vault.decrypt(vault.encrypt('secret')),'secret')
        with self.assertRaises(DomainError):vault.decrypt('invalid')

    def test_updated_revoked_connection_stops_old_task_without_platform_fallback(self):
        item=self.save();self.models.select('alice',{'connection_id':item['id']})
        old=self.models.route('alice')
        updated=self.save(id=item['id'],version=1,model='new-model')
        with self.assertRaises(DomainError):self.models.adapter(old,'alice')
        with self.assertRaises(DomainError):self.save(id=item['id'],version=1)
        self.models.delete('alice',item['id'],{'version':updated['version']})
        self.assertFalse(self.models.public('alice')['ready'])
        self.assertFalse(self.models.effective_public('alice')['ready'])
        with self.assertRaises(DomainError):self.models.route('alice')
        self.models.select('alice',{'connection_id':None})
        self.assertIsNone(self.models.route('alice'))

    def test_full_creation_uses_byok_without_platform_key_and_snapshot_survives_restart(self):
        item=self.save();self.models.select('alice',{'connection_id':item['id']})
        result=self.service.create('alice',dict(topic='课程资料整理',audience='大学生',tone='清晰',material='我用文件夹整理课程笔记。',mode='live'))
        run=self.store.get(result['run_id'],'alice');fixture=FixtureModel()
        service=Service(self.store,Config())
        service.models.vault=CredentialVault(self.store,environ={})
        def response(url,headers,payload):
            self.assertEqual(headers['Authorization'],'Bearer secret-never-public')
            value,tokens=fixture.complete(payload['messages'])
            return {'choices':[{'finish_reason':'stop','message':{'content':json.dumps(value)}}],'usage':{'total_tokens':tokens,'prompt_tokens':80,'completion_tokens':40}}
        with patch('backend.provider.connected_request',side_effect=response):
            for i in range(7):run=service.executor.step(run.run_id,'alice',run.status_version,str(i))
        self.assertEqual(run.wait_reason,'final_confirmation');self.assertEqual(len(fixture.calls),8)
        output=service.view(run)
        self.assertTrue(all(c['provider']=='qwen' and c['billing_source']=='user' for c in output['calls']))
        self.assertNotIn('secret-never-public',json.dumps(output))
        self.assertEqual(output['model_policy']['routes']['audience']['run_budget_usd'],1)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM model_audit WHERE billing_owner='alice'").fetchone()[0],8)

    def test_probe_requires_cost_ack_records_actual_usage_and_throttles(self):
        item=self.save()
        with self.assertRaises(DomainError):self.models.test('alice',item['id'],{'version':1,'acknowledge_cost':False})
        with patch('backend.provider.ConnectedModel.complete_result',return_value=({'ok':True},23,{})) as complete:
            result=self.models.test('alice',item['id'],{'version':1,'acknowledge_cost':True})
            self.assertEqual(result['tokens'],23)
            with self.assertRaises(DomainError):self.models.test('alice',item['id'],{'version':1,'acknowledge_cost':True})
            self.assertEqual(complete.call_count,1)
        self.assertEqual(self.models.public('alice')['connections'][0]['test_status'],'passed')

    def test_probe_failure_retains_reservation(self):
        item=self.save()
        with patch('backend.provider.ConnectedModel.complete_result',side_effect=DomainError('PROVIDER_ERROR','safe failure')):
            with self.assertRaises(DomainError):self.models.test('alice',item['id'],{'version':1,'acknowledge_cost':True})
        with self.store.connect() as db:
            row=db.execute('SELECT tokens,reserved,status FROM model_connection_tests').fetchone()
        self.assertEqual(row,(None,512,'failed'))

    def test_endpoint_change_cannot_reuse_old_secret_implicitly(self):
        item=self.save()
        data={k:v for k,v in item.items() if k not in ('test_status','last_tested')}
        data['base_url']='https://other.example.com/v1'
        with self.assertRaises(DomainError):self.models.save('alice',data)
        data['api_key']='new-endpoint-key'
        self.assertEqual(self.models.save('alice',data)['version'],2)

    def test_bad_urls_and_budgets_rejected(self):
        for url in ('http://api.example.com','https://127.0.0.1','https://169.254.169.254','https://localhost','https://u:p@api.example.com','https://api.example.com?a=b','https://api.example.com:8080'):
            with self.subTest(url=url),self.assertRaises(DomainError):base_url(url)
        for rate in (True,float('nan'),float('inf'),0,-1):
            with self.subTest(rate=rate),self.assertRaises(DomainError):self.save(rate_usd_per_million=rate)

    def test_transport_blocks_private_dns_before_sending_key(self):
        with patch('socket.getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]),patch('http.client.HTTPSConnection') as connection:
            with self.assertRaises(DomainError):connected_request('https://api.example.com/v1/chat/completions',{'Authorization':'secret'}, {})
        connection.assert_not_called()

    def test_all_catalog_adapters_and_anthropic_usage(self):
        for provider,item in PROVIDERS.items():
            connection={'provider':provider,'model':'example-model','base_url':item['base_url'] or 'https://api.example.com/v1'}
            response={'choices':[{'finish_reason':'stop','message':{'content':'{"ok":true}'}}],'usage':{'total_tokens':20,'prompt_tokens':12,'completion_tokens':8}}
            if provider=='anthropic':response={'stop_reason':'end_turn','content':[{'type':'text','text':'{"ok":true}'}],'usage':{'input_tokens':12,'output_tokens':8,'cache_read_input_tokens':5}}
            if provider=='openai_responses':response={'status':'completed','output':[{'type':'reasoning','summary':[]},{'type':'message','content':[{'type':'output_text','text':'{"ok":true}'}]}],'usage':{'input_tokens':12,'output_tokens':8,'total_tokens':20}}
            if provider=='minimax':response['choices'][0]['message']['content']='<think>internal</think>{"ok":true}'
            with self.subTest(provider=provider),patch('backend.provider.connected_request',return_value=response) as request:
                value,tokens,meta=ConnectedModel(connection,'secret').complete_result([{'role':'system','content':'JSON only'},{'role':'user','content':'test'}])
                self.assertTrue(value['ok']);self.assertEqual(tokens,25 if provider=='anthropic' else 20)
                if provider=='anthropic':self.assertIn('x-api-key',request.call_args.args[1])
                else:self.assertIn('Authorization',request.call_args.args[1])

    def test_responses_protocol_has_native_endpoint_output_and_usage(self):
        response={'status':'completed','id':'response-fixture','output':[{'type':'message','content':[{'type':'output_text','text':'{"ok":true}'}]}],
                  'usage':{'input_tokens':10,'output_tokens':9,'total_tokens':19}}
        item={'provider':'openai_responses','model':'codex-model-from-user','base_url':'https://api.openai.com/v1'}
        with patch('backend.provider.connected_request',return_value=response) as request:
            value,tokens,meta=ConnectedModel(item,'user-key').complete_result([{'role':'user','content':'JSON please'}])
        self.assertEqual(request.call_args.args[0],'https://api.openai.com/v1/responses')
        payload=request.call_args.args[2]
        self.assertNotIn('text',payload)
        self.assertFalse(payload['store']);self.assertIn('input',payload);self.assertNotIn('messages',payload)
        self.assertEqual((tokens,meta['input_tokens'],meta['output_tokens']),(19,10,9))
        for invalid in ({**response,'status':'incomplete'},{**response,'usage':None},
                        {**response,'output':[{'type':'message','content':[{'type':'refusal','refusal':'No'}]}]}):
            with patch('backend.provider.connected_request',return_value=invalid),self.assertRaises(DomainError):
                ConnectedModel(item,'user-key').complete_result([{'role':'user','content':'JSON please'}])

    def test_platform_budget_not_consumed_by_byok_and_byok_budget_isolated(self):
        from backend.model_router import Calls
        item=self.save();self.models.select('alice',{'connection_id':item['id']})
        router=self.service.executor.router
        run=Run(owner_id='alice',snapshot_id='test',context={'model_policy':router.policy(owner='alice')})
        with self.store.connect() as db:
            db.execute("INSERT INTO live_calls(id,run_id,agent,stage,reserved,actual,state) VALUES('expensive','other','audience','audience',10000000,10000000,'received')")
        with patch('backend.provider.ConnectedModel.complete_result',return_value=({'ok':True},12,{})):
            Calls(self.store,Config(),router).invoke(run,'audience','audience',[{'role':'user','content':'test'}],lambda db:None)
        # A different user's personal charges never consume the platform bucket.
        with self.store.connect() as db:
            billed=db.execute("SELECT billing_source,billing_owner FROM model_audit WHERE run_id=?",(run.run_id,)).fetchone()
        self.assertEqual(billed,('user','alice'))

    def test_legacy_policy_replay_hash_does_not_change_when_route_fields_grow(self):
        from backend.model_router import Calls
        from backend.workflow import digest
        config=Config('test-key')
        service=Service(self.store,config,FixtureModel())
        routes={'audience':{'provider':'fixture','model':'legacy','rate':0.0000012}}
        policy={'routes':routes,'version':digest(routes),'prompt_version':'legacy'}
        run=Run(owner_id='alice',snapshot_id='legacy-snapshot',context={'model_policy':policy})
        messages=[{'role':'system','content':'负责 audience 的'},{'role':'user','content':'{}'}]
        service.executor.calls.invoke(run,'audience','audience',messages,lambda db:None)
        expected=digest({'messages':messages,'snapshot':'legacy-snapshot','route':routes['audience']})
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT input_hash FROM model_audit').fetchone()[0],expected)


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'),'requires actual PostgreSQL')
class PostgresConnectionTests(unittest.TestCase):
    def test_byok_worker_restart_and_ledger_use_real_postgres(self):
        import psycopg
        from uuid import uuid4
        from cryptography.fernet import Fernet
        from backend.worker import Worker
        base=os.environ['TEST_DATABASE_URL'];schema='byok_test_'+uuid4().hex
        with psycopg.connect(base,autocommit=True) as db:db.execute('CREATE SCHEMA '+schema)
        try:
            target=base+('&' if '?' in base else '?')+'options=-csearch_path%3D'+schema
            with patch.dict(os.environ,{'MODEL_CREDENTIAL_KEY':Fernet.generate_key().decode()}):
                store=Store(target);service=Service(store,Config())
                item=service.models.save('owner',dict(provider='qwen',model='fixture-qwen',api_key='fake-api-key',rate_usd_per_million=2,run_budget_usd=1,day_budget_usd=5))
                service.models.select('owner',{'connection_id':item['id']})
                output=service.create('owner',dict(topic='资料整理',audience='大学生',tone='清晰',material='我用文件夹整理课程笔记。',mode='live'))
                run=store.get(output['run_id'],'owner')
                service.background('owner',run.run_id,dict(action='start',version=run.status_version,key=str(uuid4())))
                restarted=Service(Store(target),Config());fixture=FixtureModel()
                def response(url,headers,payload):
                    value,tokens=fixture.complete(payload['messages'])
                    return {'choices':[{'finish_reason':'stop','message':{'content':json.dumps(value)}}],'usage':{'total_tokens':tokens}}
                with patch('backend.provider.connected_request',side_effect=response):Worker(restarted).once()
                final=store.get(run.run_id,'owner')
                self.assertEqual(final.wait_reason,'final_confirmation')
                self.assertEqual(len(fixture.calls),8)
                with store.connect() as db:
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM model_audit WHERE billing_source='user' AND billing_owner='owner'").fetchone()[0],8)
                    self.assertGreater(db.execute('SELECT COUNT(*) FROM runtime_nodes').fetchone()[0],0)
        finally:
            with psycopg.connect(base,autocommit=True) as db:db.execute('DROP SCHEMA '+schema+' CASCADE')
