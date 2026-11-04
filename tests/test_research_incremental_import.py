import unittest
from test_research_jobs import ResearchJobsTests
from backend.contracts import DomainError
from backend.knowledge import Knowledge


class ResearchIncrementalImportTests(unittest.TestCase):
    setUp=ResearchJobsTests.setUp
    prepare=ResearchJobsTests.prepare
    packet=ResearchJobsTests.packet
    tearDown=ResearchJobsTests.tearDown

    def ready(self,key='one'):
        self.results=[dict(title='保湿参考'+str(i),url='https://example.com/'+str(i),snippet='仅搜索摘要') for i in range(3)]
        packet=self.packet(confirmation_required=True);packet['key']=key
        job=self.jobs.create('owner',packet);self.jobs.once()
        return self.jobs.get('owner',job['id'])

    def test_lead_saving_is_independent_idempotent_and_excluded_from_body_budget(self):
        job=self.ready();url=job['search_results'][0]['url']
        data={'candidate_ids':[],'lead_urls':[url],'purpose':'product_fact','key':'lead'}
        lead=self.jobs.confirm('owner',job['id'],data)
        self.assertEqual(lead['status'],'awaiting_confirmation')
        self.assertNotIn('confirmation',lead);self.assertEqual(lead['document_ids'],[])
        self.assertTrue(lead['search_results'][0]['lead_saved'])
        doc_id=lead['search_results'][0]['lead_document_id']
        doc=Knowledge(self.store).get('owner',self.account,doc_id)
        self.assertEqual(doc['metadata']['research_case']['content_kind'],'lead')
        self.assertFalse(doc['metadata']['retrieval_eligible'])
        self.assertEqual(self.jobs.confirm('owner',job['id'],data)['lead_documents'],lead['lead_documents'])
        final=self.jobs.confirm('owner',job['id'],{'candidate_ids':[c['id'] for c in job['candidates']], 'purpose':'product_fact','key':'body'})
        self.assertEqual(len(final['document_ids']),3)
        self.assertEqual(len(Knowledge(self.store).list('owner',self.account)),4)
        self.assertNotIn(doc_id,final['document_ids'])

    def test_incremental_selection_and_historical_keys_preserve_roles_and_versions(self):
        job=self.ready();a,b,c=[v['id'] for v in job['candidates']]
        first={'candidate_ids':[a],'lead_urls':[],'purpose':'product_fact','key':'first'}
        one=self.jobs.confirm('owner',job['id'],first)
        self.assertEqual(one['status'],'done')
        two=self.jobs.confirm('owner',job['id'],{'candidate_ids':[b,c],'purpose':'expression_reference','key':'second'})
        self.assertEqual(len(two['document_ids']),3)
        again=self.jobs.confirm('owner',job['id'],first)
        self.assertEqual(again['document_ids'],two['document_ids'])
        self.assertEqual(len(again['confirmed_selections']),2)
        for change in [dict(first,purpose='expression_reference'),dict(first,candidate_ids=[b]),dict(first,key='third')]:
            with self.assertRaises(DomainError) as error:self.jobs.confirm('owner',job['id'],change)
            self.assertEqual(error.exception.code,'IDEMPOTENCY_CONFLICT')
        docs=Knowledge(self.store).list('owner',self.account)
        self.assertEqual(len(docs),3);self.assertTrue(all(d['version']==1 for d in docs))

    def test_same_url_different_role_is_not_silently_reused(self):
        first=self.ready()
        a=self.jobs.confirm('owner',first['id'],{'candidate_ids':[first['candidates'][0]['id']], 'purpose':'expression_reference','key':'style'})
        second=self.ready('second')
        b=self.jobs.confirm('owner',second['id'],{'candidate_ids':[second['candidates'][0]['id']], 'purpose':'product_fact','key':'facts'})
        self.assertNotEqual(a['document_ids'],b['document_ids'])
        third=self.ready('third')
        c=self.jobs.confirm('owner',third['id'],{'candidate_ids':[third['candidates'][0]['id']], 'purpose':'product_fact','key':'reuse-facts'})
        self.assertEqual(c['document_ids'],b['document_ids'])
        self.assertEqual(len(Knowledge(self.store).list('owner',self.account)),2)

    def test_unknown_leads_and_cross_mode_keys_rejected_without_writes(self):
        job=self.ready();url=job['search_results'][0]['url']
        for urls in [[],['https://example.com/unknown'],[url,url],[url]*9]:
            with self.assertRaises(DomainError):self.jobs.confirm('owner',job['id'],{'candidate_ids':[],'lead_urls':urls,'key':'bad'})
        self.assertEqual(Knowledge(self.store).list('owner',self.account),[])
        lead={'candidate_ids':[],'lead_urls':[url],'key':'same'}
        self.jobs.confirm('owner',job['id'],lead)
        with self.assertRaises(DomainError) as err:self.jobs.confirm('owner',job['id'],{'candidate_ids':[job['candidates'][0]['id']], 'key':'same'})
        self.assertEqual(err.exception.code,'IDEMPOTENCY_CONFLICT')
        with self.assertRaises(DomainError):self.jobs.confirm('owner',job['id'],dict(lead,lead_urls=[job['search_results'][1]['url']]))
        with self.assertRaises(DomainError):self.jobs.confirm('other',job['id'],dict(lead,key='other'))

    def test_removed_saved_lead_not_reported_active(self):
        job=self.ready();url=job['search_results'][0]['url']
        saved=self.jobs.confirm('owner',job['id'],{'candidate_ids':[],'lead_urls':[url],'key':'lead'})
        doc_id=saved['search_results'][0]['lead_document_id']
        with self.store.connect() as db:db.execute("UPDATE knowledge_documents SET status='removed' WHERE id=?",(doc_id,))
        current=self.jobs.get('owner',job['id'])
        self.assertFalse(current['search_results'][0]['lead_saved'])
        self.assertIsNone(current['search_results'][0]['lead_document_id'])

    def test_incremental_import_enforces_three_body_total(self):
        import copy,json
        job=self.ready()
        self.jobs.confirm('owner',job['id'],{'candidate_ids':[c['id'] for c in job['candidates']],'key':'first-three'})
        with self.store.connect() as db:
            payload=json.loads(db.execute('SELECT payload FROM research_jobs WHERE id=?',(job['id'],)).fetchone()[0])
            extra=copy.deepcopy(payload['candidates'][0]);extra['id']='extra-body'
            extra['packet']['source_url']='https://example.com/fourth'
            extra['packet']['text']+=' 独立第四篇正文。'
            payload['candidates'].append(extra)
            payload['items'].append({'url':extra['packet']['source_url'],'title':'第四篇','candidate_id':'extra-body','status':'not_selected','body_read':True})
            db.execute('UPDATE research_jobs SET payload=? WHERE id=?',(json.dumps(payload),job['id']))
        with self.assertRaises(DomainError) as error:
            self.jobs.confirm('owner',job['id'],{'candidate_ids':['extra-body'],'key':'fourth'})
        self.assertEqual(error.exception.code,'QUOTA_EXCEEDED')
        self.assertEqual(len(self.jobs.get('owner',job['id'])['document_ids']),3)
