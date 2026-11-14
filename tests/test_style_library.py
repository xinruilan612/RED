"""Offline source-selection and four-role prompt tests; no paid model calls."""
import os
from dataclasses import asdict
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
from backend.contracts import DomainError
from backend.knowledge import Knowledge, assert_public_model_evidence
from backend.live import messages_for, normalize, schema
from backend.operations import Operations
from backend.provider import Config
from backend.service import Service
from backend.store import Store
from backend.xhs_sync import XHSSync
from test_original_retrieval import RecordingVectors


class StyleModel:
    def __init__(self): self.inputs=[]
    def complete(self,messages):
        stage=re.search(r'负责 (\w+) 的',messages[0]['content']).group(1)
        data=json.loads(messages[1]['content']);self.inputs.append((stage,data,messages[0]['content']))
        value=schema(stage)
        refs=data.get('retrieved_references',[])
        if refs:
            field={'audience':'basis','research':'prohibited_claims','strategy':'why_account','review':'limitations'}.get(stage)
            if field:
                note=refs[0]['source_id']+'：借鉴问题式标题、短句开头、分步结构与克制CTA；本题重写，不移植体验。'
                value[field]=[note] if field in ('prohibited_claims','limitations') else note
        if stage=='research':value['facts']=[]
        if stage=='body':value['selected_title']='候选一'
        if stage=='review':value['checks'][-2]['result']='unknown'
        return value,120


class StyleLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(Path(self.temp.name)/'style.sqlite')
        self.owner='owner';self.account=Operations(self.store).read(self.owner)['accounts'][0]['id']
        self.kb=Knowledge(self.store,embedding_provider=RecordingVectors(),use_configured_embeddings=False)
        self.model=StyleModel();self.service=Service(self.store,Config('fixture-key'),self.model)
        self.service.knowledge=self.kb
    def tearDown(self):self.temp.cleanup()

    def save(self, *, account=None, owner=None, case_changes=None, meta_changes=None, text=None):
        case={'evidence_role':'expression_reference','content_kind':'text','source_method':'local_browser_public_note',
              'metrics':{'likes':120,'favorites':55},'assessment':{'status':'insufficient','policy':{'max_age_days':30,'min_interactions':1000},'limitation':'测试样本'},
              'author':'测试作者','published_at':None,'observed_at':None,'collected_at':'2026-10-10T00:00:00+00:00',
              'provenance':{'visibility':'public','visibility_source':'platform_search_result','style_library_eligible':True,
                            'style_selection':{'min_likes':100,'min_favorites':50,'sort_by':'most_liked'}}}
        case.update(case_changes or {})
        metadata={'research_case':case,'retrieval_eligible':True,'evidence_role':case['evidence_role']}
        metadata.update(meta_changes or {})
        return self.kb.save(owner or self.owner,{'account_id':account or self.account,'title':'白衬衫护理案例'+str(uuid4()),
                         'text':text or ('白衬衫护理从一个具体问题开头，按分步结构说明纯棉面料冷水洗涤，最后邀请分享护理方法。'+str(uuid4()))},
                         source_type='research_case',source_url='https://www.xiaohongshu.com/explore/note-1',metadata=metadata)

    def create(self, **extra):
        data={'mode':'live','web_research':{'enabled':False,'queries':[]},'topic':'白衬衫面料护理','audience':'白衬衫学生读者','tone':'清楚','material':'纯棉面料白衬衫使用冷水清洗。',
              'scenario':'standard','allow_hypothesis':True,'operations':{'account_id':self.account,'platform':'xiaohongshu','account':'我的账号'}}
        data.update(extra);return self.service.create(self.owner,data)

    def incomplete_style_review(self, *, invalid_quote=False, invalid_excerpt=False):
        from backend.worker import Worker
        self.model=StyleModel();self.service=Service(self.store,Config('fixture-key'),self.model)
        self.service.knowledge=self.kb
        self.save();self.save()
        base=self.model.complete
        def incomplete(messages):
            value,tokens=base(messages)
            if self.model.inputs[-1][0]=='review':
                value['limitations']=['仅核对 user-material 中的事实。']
                value['checks'][-2]['result']='pass'
                value['claim_map']=[{'source_id':'user-material',
                    'quote':'不存在的来源原文' if invalid_quote else '纯棉面料白衬衫使用冷水清洗。',
                    'excerpt':'稿件没有这句话' if invalid_excerpt else '完整正文'}]
            return value,tokens
        self.model.complete=incomplete
        run_id=self.create()['run_id'];run=self.store.get(run_id,self.owner)
        self.service.background(self.owner,run_id,dict(action='start',version=run.status_version,key=str(uuid4())))
        # Reproduce a persisted review failure from the older worker so this
        # fixture exercises explicit free recovery of existing tasks.
        with patch('backend.review_recovery.conservative_review',side_effect=DomainError('MODEL_OUTPUT_INVALID','旧版本审核阻断')):
            Worker(self.service).once()
        run=self.store.get(run_id,self.owner)
        self.assertEqual(run.current_stage,'reviewer');self.assertIsNone(run.review)
        # The current worker rolls handoff failures back before marking audit
        # state. Explicitly reproduce the older persisted invalid audit in this
        # isolated fixture database, keeping its settled raw response untouched.
        with self.store.connect() as db:
            row=db.execute(f"SELECT id,response_json,actual FROM live_calls WHERE run_id=? AND stage='review' ORDER BY {self.store.order_column} DESC LIMIT 1",(run_id,)).fetchone()
            self.assertIsNotNone(row);self.assertIsNotNone(row[1]);self.assertIsNotNone(row[2])
            db.execute("UPDATE live_calls SET state='invalid' WHERE id=?",(row[0],))
            db.execute("UPDATE model_audit SET outcome='invalid' WHERE call_id=?",(row[0],))
        return run

    def test_missing_style_metadata_recovers_only_for_human_without_invented_comparison(self):
        for invalid_quote in (False,True):
            with self.subTest(invalid_quote=invalid_quote):
                run=self.incomplete_style_review(invalid_quote=invalid_quote)
                before=self.service.view(run);calls=len(self.model.inputs)
                with self.store.connect() as db:
                    audit_before=[tuple(row) for row in db.execute('SELECT * FROM live_calls WHERE run_id=?',(run.run_id,))]
                    cache_before=[tuple(row) for row in db.execute('SELECT * FROM model_audit WHERE run_id=?',(run.run_id,))]
                self.assertTrue(before['review_recovery']['available'])
                result=self.service.action(self.owner,run.run_id,dict(action='repair_review',payload={},version=run.status_version,key=str(uuid4())))
                self.assertEqual(result['run_status'],'WAITING_USER')
                self.assertEqual(result['review']['decision'],'needs_human')
                self.assertEqual(result['review']['next_action'],'request_human')
                self.assertEqual(next(c['result'] for c in result['review']['checks'] if c['name']=='originality_risk'),'unknown')
                self.assertNotIn('accept',result['allowed_actions'])
                self.assertEqual(result['usage'],before['usage']);self.assertEqual(result['calls'],before['calls'])
                self.assertEqual(len(self.model.inputs),calls)
                notes='；'.join(result['review']['limitations'])
                for reference in run.context['creation_retrieval']['groups']['examples']:
                    self.assertIn(reference['source_id'],notes)
                self.assertIn('未证明模型采用',notes);self.assertTrue(result['review']['human_questions'])
                self.assertEqual(len(result['review']['claim_map']),0)
                self.assertTrue(any(i['severity']=='major' and i['state']=='open' for i in result['review']['issues']))
                self.assertEqual(result['background']['status'],'waiting');self.assertIsNone(result['background']['error'])
                with self.store.connect() as db:
                    self.assertEqual([tuple(row) for row in db.execute('SELECT * FROM live_calls WHERE run_id=?',(run.run_id,))],audit_before)
                    self.assertEqual([tuple(row) for row in db.execute('SELECT * FROM model_audit WHERE run_id=?',(run.run_id,))],cache_before)
                current=self.store.get(run.run_id,self.owner)
                self.store.command(run.run_id,self.owner,current.status_version,str(uuid4()),'cancel',{})

    def test_missing_style_metadata_with_mismatched_draft_excerpt_requires_human(self):
        for invalid_quote in (False,True):
            with self.subTest(invalid_quote=invalid_quote):
                run=self.incomplete_style_review(invalid_quote=invalid_quote,invalid_excerpt=True)
                self.assertTrue(self.service.view(run)['review_recovery']['available'])
                calls=len(self.model.inputs)
                result=self.service.action(self.owner,run.run_id,dict(action='repair_review',payload={},version=run.status_version,key=str(uuid4())))
                self.assertEqual(result['review']['decision'],'needs_human')
                self.assertEqual(result['review']['claim_map'],[])
                self.assertIn('模型未能定位陈述',result['review']['issues'][-1]['excerpt'])
                self.assertNotIn('accept',result['allowed_actions'])
                self.assertEqual(len(self.model.inputs),calls)
                current=self.store.get(run.run_id,self.owner)
                self.store.command(run.run_id,self.owner,current.status_version,str(uuid4()),'cancel',{})

    def test_style_is_automatic_without_manual_selection_and_snapshot_is_frozen(self):
        doc=self.save()
        for knowledge in (None,{'enabled':False},{'enabled':True,'document_ids':[]}):
            with self.subTest(knowledge=knowledge):
                result=self.create(**({'knowledge':knowledge} if knowledge is not None else {}))
                run=self.store.get(result['run_id'],self.owner)
                self.assertEqual([s['document_id'] for s in run.context['evidence']],[doc['id']])
                self.assertEqual(run.context['creation_retrieval']['groups']['examples'],run.context['evidence'])
                self.store.command(run.run_id,self.owner,run.status_version,str(uuid4()),'cancel',{})
        self.kb.delete(self.owner,self.account,doc['id'],1)
        self.assertEqual(self.store.get(run.run_id,self.owner).context['evidence'],run.context['evidence'])
        self.assertEqual(self.create()['context']['evidence'],[])

    def test_eligibility_rejects_unknown_private_fact_low_metrics_and_pending(self):
        eligible=self.save(case_changes={'metrics':{'likes':101,'favorites':None}})
        for change in [{'source_method':'manual_import'},{'evidence_role':'product_fact'}, {'content_kind':'lead'},
                       {'review_required':True},{'metrics':{'likes':99,'favorites':49}},
                       {'metrics':{'likes':None,'favorites':None}}, {'provenance':{'style_library_eligible':True}},
                       {'provenance':{'visibility':'private','visibility_source':'platform_search_result','style_library_eligible':True}}]:
            self.save(case_changes=change)
        self.save(meta_changes={'retrieval_eligible':False})
        sources=self.kb.retrieve(self.owner,self.account,'白衬衫护理',style_only=True)['sources']
        self.assertEqual([s['document_id'] for s in sources],[eligible['id']])
        stranger=Operations(self.store).read('other')['accounts'][0]['id']
        self.assertEqual(self.kb.retrieve('other',stranger,'白衬衫护理',style_only=True)['sources'],[])

    def test_style_limit_uses_different_documents_and_merges_selected_facts(self):
        docs=[self.save(text=('白衬衫护理纯棉面料冷水清洗。'*130)+str(i)) for i in range(4)]
        fact=self.save(case_changes={'evidence_role':'product_fact'})
        result=self.create(knowledge={'enabled':True,'document_ids':[fact['id']]})
        ctx=result['context'];styles=ctx['creation_retrieval']['groups']['examples']
        self.assertEqual(len(styles),3);self.assertEqual(len({s['document_id'] for s in styles}),3)
        self.assertTrue(all(len(s['text'])<=700 for s in ctx['evidence']))
        self.assertIn(fact['id'],{s['document_id'] for s in ctx['evidence']})
        self.assertTrue(all(s['evidence_role']=='expression_reference' for s in styles))

    def test_all_four_roles_receive_same_references_and_persist_learning_notes(self):
        doc=self.save();result=self.create()
        for _ in range(7):
            result=self.service.action(self.owner,result['run_id'],{'action':'next','version':result['status_version'],'key':str(uuid4()),'payload':{}})
        self.assertEqual(result['wait_reason'],'final_confirmation');self.assertEqual(len(self.model.inputs),8)
        for stage,data,instruction in self.model.inputs:
            self.assertEqual(data['retrieved_references'][0]['document_id'],doc['id'])
            for phrase in ('retrieved_references','标题','开头','结构','节奏','CTA','source_id'):
                self.assertIn(phrase,instruction)
            self.assertIn('个人经历',instruction);self.assertIn('事实',instruction)
        nodes=result['node_runs'];self.assertEqual({n['agent'] for n in nodes},{'audience','research','content','reviewer'})
        for stage,field in [('audience','basis'),('research','prohibited_claims'),('strategy','why_account'),('review','limitations')]:
            value=next(n['output'] for n in nodes if n['stage']==stage)
            self.assertIn('kb:',json.dumps(value[field],ensure_ascii=False))
            self.assertIn('借鉴',json.dumps(value[field],ensure_ascii=False))

    def test_missing_reference_attribution_is_rejected_without_changing_schema(self):
        self.save();result=self.create();run=self.store.get(result['run_id'],self.owner)
        with self.assertRaises(DomainError):normalize(run,'audience',schema('audience'))
        value=schema('audience');value['basis']=run.context['evidence'][0]['source_id']+'：学习问题式开头，未证实受众结论'
        self.assertIn('basis',normalize(run,'audience',value))
        self.assertNotIn('style_learning',value)

    def test_old_own_case_is_hidden_and_previously_public_snapshot_blocks_model(self):
        with patch.object(XHSSync,'public_note_ids',return_value={'note-1'}):
            own=self.save(case_changes={'source_method':'local_browser_mcp'})
        with patch.object(XHSSync,'public_note_ids',return_value=set()):
            self.assertEqual(self.kb.retrieve(self.owner,self.account,'白衬衫护理')['sources'],[])
        with patch.object(XHSSync,'public_note_ids',return_value={'note-1'}):
            result=self.create(knowledge={'enabled':True,'document_ids':[own['id']]})
        run=self.store.get(result['run_id'],self.owner)
        self.assertTrue(run.context['evidence'])
        with patch.object(XHSSync,'public_note_ids',return_value=set()),self.store.connect() as db:
            with self.assertRaises(DomainError) as caught:assert_public_model_evidence(self.store,run,db)
        self.assertEqual(caught.exception.code,'SOURCE_VISIBILITY_CHANGED')
        with patch.object(XHSSync,'public_note_ids',return_value=set()):
            with self.assertRaises(DomainError):
                self.service.executor.calls.invoke(run,'audience','audience',messages_for(run,'audience')[0],lambda db:None)
        self.assertEqual(self.model.inputs,[])
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM live_calls').fetchone()[0],0)


    def test_private_case_is_hidden_from_library_and_all_external_case_exports(self):
        from backend.research_cases import ResearchCases
        cases=ResearchCases(self.store)
        with patch.object(XHSSync,'public_note_ids',return_value={'note-1'}):
            own=self.save(case_changes={'source_method':'local_browser_mcp'})
        public=self.save()  # Search-public sources do not use the own-account whitelist.
        refs=[{'document_id':own['id'],'version':1}]
        with patch.object(XHSSync,'public_note_ids',return_value=set()):
            self.assertEqual([d['id'] for d in self.kb.list(self.owner,self.account)],[public['id']])
            with self.assertRaises(DomainError):self.kb.get(self.owner,self.account,own['id'])
            self.assertEqual(self.kb.get(self.owner,self.account,public['id'])['id'],public['id'])
            report=cases.export(self.owner,self.account)
            self.assertEqual(report['count'],1);self.assertNotIn(own['title'],report['content'])
            with self.assertRaises(DomainError):cases.export(self.owner,self.account,[own['id']])
            with self.assertRaises(DomainError):cases.export_versions(self.owner,self.account,refs)
            audit=self.kb.get_version(self.owner,self.account,own['id'],1)
            self.assertEqual(audit['title'],own['title']);self.assertTrue(audit['chunks'])
            self.assertEqual(cases.export_versions(self.owner,self.account,[{'document_id':public['id'],'version':1}])['count'],1)

    def test_cached_and_failed_job_reports_hide_private_sources_without_deleting_audit(self):
        from backend.research_jobs import ResearchJobs
        jobs=ResearchJobs(self.store)
        with patch.object(XHSSync,'public_note_ids',return_value={'note-1'}):
            own=self.save(case_changes={'source_method':'local_browser_mcp'})
        public=self.save()
        for kind in ('saved','failed','public'):
            packet={'account_id':self.account,'queries':['白衬衫护理'],'provider':'bing','targets':['web'],
                    'evidence_role':'expression_reference','permission_confirmed':True,'key':kind}
            job=jobs.create(self.owner,packet);identity=job['id']
            doc=public if kind=='public' else own
            item={'title':doc['title'],'url':doc['source_url'],'status':'failed' if kind=='failed' else 'saved'}
            if kind!='failed':item.update(document_id=doc['id'],version=1)
            with self.store.connect() as db:
                row=db.execute('SELECT payload FROM research_jobs WHERE id=?',(identity,)).fetchone()
                payload=json.loads(row[0]);payload.update(items=[item],report={'content':doc['title']+' SECRET-BODY','count':1})
                db.execute("UPDATE research_jobs SET status='done',payload=? WHERE id=?",(json.dumps(payload),identity))
            with patch.object(XHSSync,'public_note_ids',return_value=set()):
                if kind=='public':
                    self.assertEqual(jobs.export(self.owner,identity)['count'],1)
                    self.assertIn('SECRET-BODY',jobs.get(self.owner,identity)['report']['content'])
                    continue
                for visible in (jobs.get(self.owner,identity),next(j for j in jobs.list(self.owner,self.account) if j['id']==identity),jobs.cancel(self.owner,identity),jobs.create(self.owner,packet)):
                    serialized=json.dumps(visible,ensure_ascii=False)
                    self.assertNotIn(doc['title'],serialized);self.assertNotIn('SECRET-BODY',serialized)
                    self.assertEqual(visible['error'],'SOURCE_VISIBILITY_CHANGED')
                with self.assertRaises(DomainError):jobs.export(self.owner,identity)
                with self.store.connect() as db:
                    self.assertIn('SECRET-BODY',db.execute('SELECT payload FROM research_jobs WHERE id=?',(identity,)).fetchone()[0])


    def test_simulated_old_run_and_export_are_hidden_after_visibility_revocation(self):
        with patch.object(XHSSync,'public_note_ids',return_value={'note-1'}):
            own=self.save(case_changes={'source_method':'local_browser_mcp'})
            result=self.create(mode='simulation',knowledge={'enabled':True,'document_ids':[own['id']]})
        run=self.store.get(result['run_id'],self.owner)
        before=asdict(self.store.get(run.run_id,self.owner))
        with patch.object(XHSSync,'public_note_ids',return_value=set()):
            for action in (lambda:self.service.view(run),lambda:self.service.export(self.owner,run.run_id)):
                with self.assertRaises(DomainError) as caught:action()
                self.assertEqual(caught.exception.code,'SOURCE_VISIBILITY_CHANGED')
                self.assertNotIn(own['title'],str(caught.exception))
                self.assertIn('历史任务内容已隐藏',str(caught.exception))
        self.assertEqual(asdict(self.store.get(run.run_id,self.owner)),before)
        self.assertEqual(self.model.inputs,[])
        with patch.object(XHSSync,'public_note_ids',return_value={'note-1'}):
            self.assertEqual(self.service.view(run)['run_id'],run.run_id)

    def test_missing_source_version_blocks_old_task_display_conservatively(self):
        self.save();result=self.create(mode='simulation');run=self.store.get(result['run_id'],self.owner)
        source=run.context['evidence'][0]
        with self.store.connect() as db:
            db.execute('DELETE FROM knowledge_chunks WHERE document_id=?',(source['document_id'],))
            db.execute('DELETE FROM knowledge_versions WHERE document_id=?',(source['document_id'],))
            db.execute('DELETE FROM knowledge_documents WHERE id=?',(source['document_id'],))
        for action in (lambda:self.service.view(run),lambda:self.service.export(self.owner,run.run_id)):
            with self.assertRaises(DomainError) as caught:action()
            self.assertEqual(caught.exception.code,'SOURCE_VISIBILITY_CHANGED')
        self.assertTrue(self.store.get(run.run_id,self.owner).context['evidence'])


    def test_windtunnel_material_snapshots_use_same_visibility_gate(self):
        with patch.object(XHSSync,'public_note_ids',return_value={'note-1'}):
            own=self.save(case_changes={'source_method':'local_browser_mcp'})
            result=self.service.create(self.owner,{'workflow_type':'windtunnel','account_id':self.account,
                         'title':'白衬衫护理','text':'阅读护理步骤。','mode':'simulation',
                         'knowledge':[{'document_id':own['id'],'version':1}]})
        run=self.store.get(result['run_id'],self.owner)
        with patch.object(XHSSync,'public_note_ids',return_value=set()):
            for action in (lambda:self.service.view(run),lambda:self.service.export(self.owner,run.run_id)):
                with self.assertRaises(DomainError) as caught:action()
                self.assertEqual(caught.exception.code,'SOURCE_VISIBILITY_CHANGED')
        self.assertTrue(self.store.get(run.run_id,self.owner).windtunnel['sources'])


    def test_windtunnel_imported_draft_cannot_bypass_origin_visibility(self):
        with patch.object(XHSSync,'public_note_ids',return_value={'note-1'}):
            own=self.save(case_changes={'source_method':'local_browser_mcp'})
            original=self.create(mode='simulation',knowledge={'enabled':True,'document_ids':[own['id']]})
            for _ in range(7):
                original=self.service.action(self.owner,original['run_id'],{'action':'next','version':original['status_version'],'key':str(uuid4()),'payload':{}})
            source=self.store.get(original['run_id'],self.owner)
            result=self.service.create(self.owner,{'workflow_type':'windtunnel','account_id':self.account,'mode':'simulation',
                      'import':{'run_id':source.run_id,'draft_ref':source.drafts[-1]['ref']}})
        run=self.store.get(result['run_id'],self.owner)
        with patch.object(XHSSync,'public_note_ids',return_value=set()):
            with self.assertRaises(DomainError) as caught:self.service.view(run)
            self.assertEqual(caught.exception.code,'SOURCE_VISIBILITY_CHANGED')
        self.assertTrue(self.store.get(run.run_id,self.owner).windtunnel['drafts'])


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'PostgreSQL integration requires TEST_DATABASE_URL')
class PostgresStyleLibraryTests(StyleLibraryTests):
    def setUp(self):
        import psycopg
        self.temp=tempfile.TemporaryDirectory();self.schema='youji_test_style_'+uuid4().hex
        self.base=os.environ['TEST_DATABASE_URL']
        with psycopg.connect(self.base,autocommit=True) as db:db.execute('CREATE SCHEMA '+self.schema)
        self.store=Store(self.base+('&' if '?' in self.base else '?')+'options=-csearch_path%3D'+self.schema)
        self.owner='owner';self.account=Operations(self.store).read(self.owner)['accounts'][0]['id']
        self.kb=Knowledge(self.store,embedding_provider=RecordingVectors(),use_configured_embeddings=False)
        self.model=StyleModel();self.service=Service(self.store,Config('fixture-key'),self.model)
        self.service.knowledge=self.kb
    def tearDown(self):
        import psycopg
        with psycopg.connect(self.base,autocommit=True) as db:db.execute('DROP SCHEMA '+self.schema+' CASCADE')
        self.temp.cleanup()
