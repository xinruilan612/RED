import os
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4
from backend.contracts import DomainError
from backend.knowledge import Knowledge
from backend.operations import Operations
from backend.research_cases import ResearchCases
from backend.store import Store


class ResearchCaseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.temp.name)/'cases.sqlite')
        self.cases=ResearchCases(self.store)
        self.owner='owner'
        self.account=Operations(self.store).read(self.owner)['accounts'][0]['id']

    def tearDown(self):
        self.temp.cleanup()

    def packet(self,**overrides):
        return dict(account_id=self.account,title='护肤案例',text='日常护肤推荐先清洁再涂抹保湿乳液。这是一份结构参考，不证明用户产品具有这些效果。',
                    source_url='https://example.com/skincare',platform='xiaohongshu',author='测试作者',
                    published_at='2025-01-01T00:00:00+00:00',observed_at='2025-01-02T00:00:00+00:00',
                    permission_confirmed=True,**overrides)

    def test_case_missing_metrics_and_fact_role_survive_rag(self):
        doc=self.cases.save(self.owner,self.packet(metrics={'likes':1200},evidence_role='expression_reference'))
        case=doc['metadata']['research_case']
        self.assertIsNone(case['metrics']['views'])
        self.assertIsNone(case['assessment']['interaction_rate'])
        self.assertEqual(case['assessment']['status'],'high_interaction_candidate')
        kb=Knowledge(self.store,use_configured_embeddings=False)
        sources=kb.retrieve(self.owner,self.account,'护肤保湿乳液')['sources']
        self.assertEqual(sources[0]['evidence_role'],'expression_reference')
        self.assertEqual(sources[0]['case_ref']['document_id'],doc['id'])
        self.assertNotIn('original_base64',doc)
        self.assertNotIn('original_base64',self.cases.list(self.owner,self.account)[0])

    def test_leads_excluded_and_owner_scoped(self):
        doc=self.cases.save(self.owner,self.packet(content_kind='lead'))
        result=Knowledge(self.store,use_configured_embeddings=False).retrieve(self.owner,self.account,'护肤保湿乳液')
        self.assertTrue(result['insufficient'])
        other=Operations(self.store).read('other')['accounts'][0]['id']
        self.assertEqual(self.cases.list('other',other),[])
        with self.assertRaises(DomainError):self.cases.export('other',other,[doc['id']])
        with self.assertRaises(DomainError):self.cases.save(self.owner,self.packet(content_kind='lead',evidence_role='product_fact'))

    def test_metrics_invalid_times_and_permission_rejected(self):
        for field in ({'metrics':{'views':-1}},{'metrics':{'likes':True}},{'metrics':{'extra':1}},
                      {'metrics':{'likes':10},'observed_at':None},{'published_at':'2025-01-03T00:00:00Z'},
                      {'permission_confirmed':False},{'observed_at':'2025-01-02'},{'policy':{}}):
            packet=self.packet();packet.update(field)
            with self.subTest(field=field),self.assertRaises(DomainError):
                self.cases.save(self.owner,packet)

    def test_export_versions_dedup_and_deleted_case(self):
        packet=self.packet();packet['text']=('保湿乳液素材正文。'*100)+'<script>alert(1)</script> ![image](https://example.com/x)'
        doc=self.cases.save(self.owner,packet)
        with self.assertRaises(DomainError):self.cases.save(self.owner,packet)
        exported=self.cases.export(self.owner,self.account)
        self.assertEqual(exported['count'],1)
        self.assertEqual(exported['content'].count('保湿乳液素材正文。'),100)
        self.assertIn('未知',exported['content'])
        self.assertNotIn('<script>',exported['content'])
        self.assertNotIn('![image]',exported['content'])
        packet.update(document_id=doc['id'],expected_version=1,text='全新控油资料内容，仅用于新的商品事实核验。',evidence_role='product_fact')
        newer=self.cases.save(self.owner,packet)
        self.assertEqual(newer['version'],2)
        with self.assertRaises(DomainError):self.cases.save(self.owner,packet)
        self.cases.knowledge.delete(self.owner,self.account,doc['id'],2)
        self.assertEqual(self.cases.export(self.owner,self.account)['count'],0)

    def test_generic_update_cannot_upgrade_lead_or_erase_case_role(self):
        for kind,role in (('lead','expression_reference'),('text','product_fact')):
            packet=self.packet(content_kind=kind,evidence_role=role)
            packet['text']+=' '+kind
            doc=self.cases.save(self.owner,packet)
            with self.assertRaises(DomainError) as caught:
                self.cases.knowledge.save(self.owner,dict(account_id=self.account,title='仅改标题',
                    text=packet['text'],document_id=doc['id'],expected_version=1))
            self.assertEqual(caught.exception.code,'CASE_EDIT_REQUIRED')
            unchanged=self.cases.knowledge.get(self.owner,self.account,doc['id'])
            self.assertEqual(unchanged['version'],1)
            self.assertEqual(unchanged['source_type'],'research_case')
            self.assertEqual(unchanged['metadata']['evidence_role'],role)
            self.assertEqual(unchanged['metadata']['retrieval_eligible'],kind!='lead')
            # The typed case endpoint remains editable without changing the category.
            packet.update(document_id=doc['id'],expected_version=1,title='案例专用修订')
            updated=self.cases.save(self.owner,packet)
            self.assertEqual(updated['version'],2)
            self.assertEqual(updated['metadata']['research_case']['content_kind'],kind)

    def test_frozen_report_survives_edits_and_removal_with_owner_isolation(self):
        packet=self.packet();doc=self.cases.save(self.owner,packet)
        refs=[{'document_id':doc['id'],'version':1}]
        before=self.cases.export_versions(self.owner,self.account,refs)
        packet.update(document_id=doc['id'],expected_version=1,title='修订后不同标题',text='新的材料不应改变旧研究报告。')
        self.cases.save(self.owner,packet)
        self.cases.knowledge.delete(self.owner,self.account,doc['id'],2)
        self.assertEqual(self.cases.export_versions(self.owner,self.account,refs),before)
        self.assertIn('冻结案例版本',before['content'])
        self.assertNotIn('修订后不同标题',before['content'])
        self.assertTrue(Knowledge(self.store,use_configured_embeddings=False).retrieve(self.owner,self.account,'护肤保湿乳液')['insufficient'])
        other=Operations(self.store).read('other')['accounts'][0]['id']
        with self.assertRaises(DomainError):self.cases.export_versions('other',other,refs)
        with self.assertRaises(DomainError):self.cases.export_versions(self.owner,self.account,[{'document_id':doc['id'],'version':999}])
        self.assertNotIn('original_base64',self.cases.knowledge.get_version(self.owner,self.account,doc['id'],1))

    def test_transaction_hooks_roll_back_document_and_versions(self):
        def reject(db):
            raise DomainError('CANCELLED','任务已取消')
        with self.assertRaises(DomainError):
            self.cases.save(self.owner,self.packet(),transaction_guard=reject)
        self.assertEqual(self.cases.list(self.owner,self.account),[])
        def fail_after_save(db,identity,version):
            self.assertEqual(version,1)
            self.assertIsNotNone(db.execute('SELECT id FROM knowledge_documents WHERE id=?',(identity,)).fetchone())
            raise DomainError('LEASE_LOST','租约已失效')
        with self.assertRaises(DomainError):
            self.cases.save(self.owner,self.packet(),transaction_saved=fail_after_save)
        self.assertEqual(self.cases.list(self.owner,self.account),[])

    def test_already_read_article_import_carries_provenance_and_blocks_xhs(self):
        article={'title':'品牌官网护肤说明','text':'保湿乳液应当按照产品标签的使用方法涂抹，注意避开眼周并核对成分。',
                 'url':'https://example.com/product','fetched_at':'2025-01-02T00:00:00Z','verification':'已读取'}
        doc=self.cases.from_article(self.owner,self.account,article,evidence_role='product_fact',permission_confirmed=True)
        self.assertEqual(doc['metadata']['research_case']['source_method'],'read_public_web')
        for url in ('https://www.xiaohongshu.com/explore/a','https://xhslink.com/a'):
            with self.assertRaises(DomainError):
                self.cases.from_article(self.owner,self.account,{**article,'url':url},permission_confirmed=True)
        with self.assertRaises(DomainError):
            self.cases.from_article(self.owner,self.account,{'url':article['url'],'snippet':'摘要'},permission_confirmed=True)


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'),'PostgreSQL integration requires TEST_DATABASE_URL')
class PostgresResearchCaseTests(ResearchCaseTests):
    def setUp(self):
        import psycopg
        self.temp=tempfile.TemporaryDirectory();self.schema='youji_test_cases_'+uuid4().hex
        self.base=os.environ['TEST_DATABASE_URL']
        with psycopg.connect(self.base,autocommit=True) as db:db.execute('CREATE SCHEMA '+self.schema)
        self.store=Store(self.base+('&' if '?' in self.base else '?')+'options=-csearch_path%3D'+self.schema)
        self.cases=ResearchCases(self.store);self.owner='owner'
        self.account=Operations(self.store).read(self.owner)['accounts'][0]['id']

    def tearDown(self):
        import psycopg
        with psycopg.connect(self.base,autocommit=True) as db:db.execute('DROP SCHEMA '+self.schema+' CASCADE')
        self.temp.cleanup()
