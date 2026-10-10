"""Offline source-selection and four-role prompt tests; no paid model calls."""
import os
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
        self.kb=Knowledge(self.store,use_configured_embeddings=False)
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
        data={'mode':'live','topic':'白衬衫面料护理','audience':'白衬衫学生读者','tone':'清楚','material':'纯棉面料白衬衫使用冷水清洗。',
              'scenario':'standard','allow_hypothesis':True,'operations':{'account_id':self.account,'platform':'xiaohongshu','account':'我的账号'}}
        data.update(extra);return self.service.create(self.owner,data)

    def test_style_is_automatic_without_manual_selection_and_snapshot_is_frozen(self):
        doc=self.save()
        for knowledge in (None,{'enabled':False},{'enabled':True,'document_ids':[]}):
            with self.subTest(knowledge=knowledge):
                result=self.create(**({'knowledge':knowledge} if knowledge is not None else {}))
                run=self.store.get(result['run_id'],self.owner)
                self.assertEqual([s['document_id'] for s in run.context['evidence']],[doc['id']])
                self.assertEqual(run.context['style_retrieval']['sources'],run.context['evidence'])
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
        ctx=result['context'];styles=ctx['style_retrieval']['sources']
        self.assertEqual(len(styles),3);self.assertEqual(len({s['document_id'] for s in styles}),3)
        self.assertTrue(all(len(s['text'])<=400 for s in ctx['evidence']))
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
            self.assertIn('不能把案例中的产品功效',instruction)
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


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'PostgreSQL integration requires TEST_DATABASE_URL')
class PostgresStyleLibraryTests(StyleLibraryTests):
    def setUp(self):
        import psycopg
        self.temp=tempfile.TemporaryDirectory();self.schema='youji_test_style_'+uuid4().hex
        self.base=os.environ['TEST_DATABASE_URL']
        with psycopg.connect(self.base,autocommit=True) as db:db.execute('CREATE SCHEMA '+self.schema)
        self.store=Store(self.base+('&' if '?' in self.base else '?')+'options=-csearch_path%3D'+self.schema)
        self.owner='owner';self.account=Operations(self.store).read(self.owner)['accounts'][0]['id']
        self.kb=Knowledge(self.store,use_configured_embeddings=False)
        self.model=StyleModel();self.service=Service(self.store,Config('fixture-key'),self.model)
        self.service.knowledge=self.kb
    def tearDown(self):
        import psycopg
        with psycopg.connect(self.base,autocommit=True) as db:db.execute('DROP SCHEMA '+self.schema+' CASCADE')
        self.temp.cleanup()
