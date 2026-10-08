"""Offline regression: compound reviewer errors remain recoverable, never approved."""
import copy
import json
import sqlite3
import time
import unittest
from types import SimpleNamespace

from backend.contracts import DomainError
from backend.live import schema
from backend.review_recovery import candidate
from backend.workflow import Run


class DayOneReviewRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.run=Run('owner','snapshot',context={'mode':'live','material':'原始材料中的事实。'})
        self.run.start()
        self.run.branch('audience','snapshot','succeeded',{'sample_size':0})
        self.run.branch('research','snapshot','succeeded',{'core_gap':False})
        self.run.join(True)
        self.run.draft({'selected_title':'标题事实','body':'正文事实','cta':'互动问题','tags':['事实标签']})
        self.run.prior_review={'issues':[{'issue_id':'current','severity':'major','state':'open'}]}
        self.run.reviews=[{'issues':[{'issue_id':'historical'}]},self.run.prior_review]
        self.raw=schema('review')
        self.raw.update(decision='revision_required',next_action='revise',issues=[{
            'issue_id':'still-open','severity':'major','state':'open','location':'body',
            'excerpt':'正文事实','reason':'事实仍需核对','suggestion':'核对材料后修改'}],
            previous_issue_results=[{'issue_id':'current','result':'unresolved'},
                                    {'issue_id':'historical','result':'unresolved'}],
            claim_map=[{'excerpt':'标题事实','source_id':'user-material','quote':'不存在的材料'},
                       {'excerpt':'正文事实','source_id':'user-material','quote':' 原始材料中的事实。\n'}])
        self.db=sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.executescript("""
            CREATE TABLE runtime_jobs(run_id TEXT,status TEXT);
            CREATE TABLE live_steps(run_id TEXT,state TEXT);
            CREATE TABLE live_calls(id TEXT,run_id TEXT,stage TEXT,state TEXT,response_json TEXT,actual INTEGER);
            CREATE TABLE model_audit(call_id TEXT,snapshot_id TEXT,started REAL);
        """)
        self.db.execute('INSERT INTO live_calls VALUES(?,?,?,?,?,?)',
                        ('call',self.run.run_id,'review','invalid',json.dumps(self.raw),120))
        self.db.execute('INSERT INTO model_audit VALUES(?,?,?)',('call','snapshot',time.time()))
        self.store=SimpleNamespace(order_column='rowid')

    def recover(self):
        self.db.execute('UPDATE live_calls SET response_json=?',(json.dumps(self.raw),))
        return candidate(self.db,self.store,self.run)

    def test_compound_errors_preserve_current_unresolved_and_raw_audit(self):
        before=copy.deepcopy(self.raw)
        call,report,removed,excluded=self.recover()
        self.assertEqual(call,'call')
        self.assertEqual(report['decision'],'revision_required')
        self.assertEqual(report['previous_issue_results'],[{'issue_id':'current','result':'unresolved'}])
        self.assertEqual(excluded,[{'issue_id':'historical','result':'unresolved'}])
        self.assertEqual(removed,[self.raw['claim_map'][0]])
        self.assertEqual(report['claim_map'],[{'excerpt':'正文事实','source_id':'user-material','quote':'原始材料中的事实。'}])
        self.assertEqual(json.loads(self.db.execute('SELECT response_json FROM live_calls').fetchone()[0]),before)
        self.assertEqual(self.raw,before)
        self.assertEqual(next(c['result'] for c in report['checks'] if c['name']=='evidence_integrity'),'fail')
        self.assertEqual(report['issues'][0],before['issues'][0])
        self.assertIsNone(self.run.accepted_ref)

    def test_recovery_locates_title_cta_and_tags_and_assigns_mapping_to_reviewer(self):
        for field,excerpt in [('selected_title','标题事实'),('body','正文事实'),('cta','互动问题'),('tags','事实标签')]:
            with self.subTest(field=field):
                self.raw['claim_map'][0]['excerpt']=excerpt
                report=self.recover()[1]
                issue=report['issues'][-1]
                self.assertEqual(issue['location'],field)
                self.assertEqual(issue['excerpt'],excerpt)
                self.assertIn('引用映射由审核角色',issue['suggestion'])
                self.assertIn('不要把 claim_map 写进正文',issue['suggestion'])

    def test_missing_conflicting_unknown_or_invalid_current_result_remains_blocked(self):
        variants=[[],[{'issue_id':'current','result':'unresolved'},{'issue_id':'current','result':'resolved'}],
                  [{'issue_id':'current','result':'unresolved'},{'issue_id':'unknown','result':'resolved'}],
                  [{'issue_id':'current','result':'invented'},{'issue_id':'historical','result':'resolved'}]]
        for results in variants:
            with self.subTest(results=results):
                self.raw['previous_issue_results']=results
                with self.assertRaises(DomainError):self.recover()

    def test_identical_prior_result_duplicate_recovers_without_resolving_issue(self):
        self.raw['previous_issue_results']=[{'issue_id':'current','result':'unresolved'}]*2
        report=self.recover()[1]
        self.assertEqual(report['previous_issue_results'],[{'issue_id':'current','result':'unresolved'}])
        self.assertNotEqual(report['decision'],'approved')

    def test_compound_recovery_cannot_hide_malformed_checks_or_unknown_usage(self):
        self.raw['checks']=[]
        with self.assertRaises(DomainError):self.recover()
        self.raw['checks']=schema('review')['checks']
        self.db.execute('UPDATE live_calls SET actual=NULL')
        with self.assertRaises(DomainError):self.recover()

    def test_historical_ids_and_empty_revision_only_recover_with_original_human_questions(self):
        self.raw.update(issues=[],claim_map=[],human_questions=['请补充使用场景资料'])
        before=copy.deepcopy(self.raw)
        report=self.recover()[1]
        self.assertEqual(report['decision'],'needs_human')
        self.assertEqual(report['next_action'],'request_human')
        self.assertEqual(report['issues'],[])
        self.assertEqual(report['human_questions'],before['human_questions'])
        self.assertEqual(report['previous_issue_results'],[{'issue_id':'current','result':'unresolved'}])
        self.assertEqual(self.raw,before)
        self.raw['human_questions']=[]
        with self.assertRaises(DomainError):self.recover()

    def test_live_hypothesis_permission_explains_missing_history_and_requires_consent(self):
        run=Run('owner','snapshot',context={'mode':'live','material':'公开产品资料'})
        run.start()
        run.branch('audience','snapshot','succeeded',{'sample_size':0})
        run.branch('research','snapshot','succeeded',{'core_gap':False})
        run.join(False)
        self.assertEqual(run.wait_reason,'hypothesis_permission')
        with self.assertRaises(DomainError) as caught:
            run.demo_supplement('公开产品资料',False)
        self.assertIn('当前没有可用受众历史',str(caught.exception))
        self.assertNotIn('模拟版',str(caught.exception))
        self.assertEqual(run.wait_reason,'hypothesis_permission')
        self.assertEqual(run.snapshot_id,'snapshot')
        run.demo_supplement('公开产品资料',True)
        self.assertEqual(run.run_status,'QUEUED')
        self.assertTrue(run.context['allow_hypothesis'])
        self.assertEqual(run.context['material'],'公开产品资料')
        self.assertNotEqual(run.snapshot_id,'snapshot')

    def test_obsolete_ids_alone_cannot_create_approval(self):
        self.raw.update(decision='approved',next_action='await_user_confirmation',issues=[],claim_map=[])
        with self.assertRaises(DomainError):self.recover()

    def test_unlocated_excerpt_is_explicitly_whole_body_not_invented_location(self):
        self.raw['claim_map'][0]['excerpt']='旧稿片段'
        report=self.recover()[1]
        self.assertEqual(report['issues'][-1]['location'],'body')
        self.assertEqual(report['issues'][-1]['excerpt'],'正文事实')
        self.assertEqual(report['decision'],'revision_required')


if __name__=='__main__':unittest.main()
