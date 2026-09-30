"""Executable service-domain tests, without models, HTTP, or synthetic quality claims."""
import copy
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from backend.contracts import CONTRACT, PARAMETERS, DomainError, legacy_candidate, tool_allowed
from backend.store import Store


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name)/'test.sqlite')
        self.run = self.store.create('alice','snapshot-1')
        self.key = 0

    def command(self, action, **payload):
        self.key += 1
        self.run = self.store.command(self.run.run_id, 'alice', self.run.status_version, str(self.key), action, payload)
        return self.run

    def ready(self, core_gap=False, samples=0, allowed=True):
        self.command('start')
        for agent, data in [('research',{'core_gap':core_gap}), ('audience',{'sample_size':samples})]:
            self.command('branch', agent=agent, snapshot_id='snapshot-1', outcome='succeeded', data=data)
        self.command('join', allow_hypothesis=allowed)

    def draft(self):
        self.ready()
        self.command('draft', content={'body':'尝试整理一条资料，检查结果是否有用。'})

    def report(self, decision='approved'):
        draft = self.run.drafts[-1]
        return {'ref':'review-'+str(len(self.run.drafts)), 'draft_ref':draft['ref'],
                'snapshot_id':draft['snapshot_id'], 'content_hash':draft['content_hash'], 'policy_ref':'policy@1',
                'decision':decision, 'next_action':{'approved':'await_user_confirmation','revision_required':'revise','needs_human':'request_human'}[decision],
                'checks':[{'name':name,'result':'pass'} for name in CONTRACT['review_policy']['checks']],
                'issues':[], 'previous_issue_results':[], 'limitations':[], 'human_questions':[]}

    def review(self, report=None, gates=None):
        self.command('reviewed', report=report or self.report(), gates=gates or {k:True for k in CONTRACT['review_policy']['required_gates']})

    def assert_code(self, code, fn):
        with self.assertRaises(DomainError) as err:
            fn()
        self.assertEqual(err.exception.code, code)

    def test_accept_requires_review_and_exact_version(self):
        self.draft()
        self.assert_code('INVALID_TRANSITION',lambda:self.command('accept',draft_ref=self.run.drafts[-1]['ref'],review_ref='fake'))
        self.review()
        self.assertEqual(self.run.run_status,'WAITING_USER')
        self.assert_code('VERSION_CONFLICT',lambda:self.command('accept',draft_ref='stale',review_ref=self.run.review['ref']))
        self.command('accept',draft_ref=self.run.drafts[-1]['ref'],review_ref=self.run.review['ref'])
        self.assertEqual(self.run.run_status,'SUCCEEDED')
        self.assert_code('INVALID_TRANSITION',lambda:self.command('start'))

    def test_edit_invalidates_review_and_keeps_old_draft(self):
        self.draft(); self.review()
        old = copy.deepcopy(self.run.drafts[-1])
        self.command('edit',content={'body':'新的人工修改稿'})
        self.assertEqual(self.run.drafts[0],old)
        self.assertIsNone(self.run.review)
        self.assertEqual(self.run.current_stage,'reviewer')
        self.assert_code('INVALID_TRANSITION',lambda:self.command('accept',draft_ref=old['ref'],review_ref='review-1'))
        self.review()
        self.command('accept',draft_ref=self.run.drafts[-1]['ref'],review_ref=self.run.review['ref'])
        self.assertNotEqual(self.run.accepted_ref,old['ref'])

    def test_cold_start_requires_explicit_permission(self):
        self.ready(allowed=False)
        self.assertEqual(self.run.wait_reason,'hypothesis_permission')
        self.assert_code('INVALID_TRANSITION',lambda:self.command('draft',content={'body':'不能越过暂停'}))

    def test_core_gap_pauses_and_supplement_invalidates_both_branches(self):
        self.ready(core_gap=True)
        self.assertEqual(self.run.wait_reason,'missing_material')
        self.command('supplement',snapshot_id='snapshot-2')
        self.assertEqual(self.run.branches,{})
        self.command('start')
        self.assert_code('VERSION_CONFLICT',lambda:self.command('branch',agent='audience',snapshot_id='snapshot-1',outcome='succeeded',data={'sample_size':2}))
        for a,d in [('audience',{'sample_size':2}),('research',{'core_gap':True})]:
            self.command('branch',agent=a,snapshot_id='snapshot-2',outcome='succeeded',data=d)
        self.command('join',allow_hypothesis=True)
        self.assert_code('SUPPLEMENT_LIMIT',lambda:self.command('supplement',snapshot_id='snapshot-3'))

    def test_failed_branch_not_empty_success_and_retry_preserves_sibling(self):
        self.command('start')
        self.command('branch',agent='audience',snapshot_id='snapshot-1',outcome='succeeded',data={'sample_size':0})
        self.command('branch',agent='research',snapshot_id='snapshot-1',outcome='retryable_error')
        self.assert_code('INVALID_TRANSITION',lambda:self.command('join',allow_hypothesis=True))
        self.command('retry'); self.command('start')
        self.assertEqual(set(self.run.branches),{'audience'})
        self.command('branch',agent='research',snapshot_id='snapshot-1',outcome='succeeded',data={'core_gap':False})
        self.command('join',allow_hypothesis=True)
        self.assertEqual(self.run.current_stage,'content')

    def test_incomplete_join_and_late_cancelled_results_rejected(self):
        self.command('start')
        self.assert_code('JOIN_INCOMPLETE',lambda:self.command('join',allow_hypothesis=True))
        self.command('cancel')
        self.assert_code('INVALID_TRANSITION',lambda:self.command('branch',agent='audience',snapshot_id='snapshot-1',outcome='succeeded',data={'sample_size':1}))

    def test_duplicate_command_and_conflicting_reuse(self):
        old = self.run
        first = self.store.command(old.run_id,'alice',0,'stable','start')
        second = self.store.command(old.run_id,'alice',0,'stable','start')
        self.assertEqual(first.events,second.events)
        self.assert_code('IDEMPOTENCY_CONFLICT',lambda:self.store.command(old.run_id,'alice',0,'stable','cancel'))
        self.assert_code('VERSION_CONFLICT',lambda:self.store.command(old.run_id,'alice',0,'another','cancel'))

    def test_cross_owner_and_single_active_run(self):
        self.assert_code('RESOURCE_NOT_FOUND',lambda:self.store.get(self.run.run_id,'bob'))
        self.assert_code('RESOURCE_NOT_FOUND',lambda:self.store.command(self.run.run_id,'bob',0,'x','start'))
        self.assert_code('RUN_ALREADY_ACTIVE',lambda:self.store.create('alice','other'))
        self.command('cancel')
        self.assertNotEqual(self.store.create('alice','other').run_id,self.run.run_id)

    def test_reopen_preserves_state_and_ordered_events(self):
        self.draft(); self.review()
        reopened = Store(self.store.path).get(self.run.run_id,'alice')
        self.assertEqual(reopened,self.run)
        self.assertEqual([e['seq'] for e in reopened.events],list(range(1,len(reopened.events)+1)))

    def test_invalid_reviews_rollback_transaction(self):
        self.draft()
        mutations = [lambda r:r['checks'].pop(), lambda r:r['checks'].append(r['checks'][0]),
                     lambda r:r.update(next_action='revise'), lambda r:r.update(draft_ref='old'),
                     lambda r:r['checks'][0].update(result='unknown'),
                     lambda r:r['issues'].append({'issue_id':'x','severity':'major','state':'open'})]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                report=self.report(); mutate(report)
                with self.assertRaises(DomainError): self.review(report)
                self.assertEqual(self.store.get(self.run.run_id,'alice'),self.run)

    def test_unknown_originality_requires_disclosed_limits(self):
        self.draft(); report=self.report()
        next(c for c in report['checks'] if c['name']=='originality_risk')['result']='unknown'
        self.assert_code('REVIEW_GATE_FAILED',lambda:self.review(report))
        report['limitations']=['仅检查提供的素材，未全网查重']
        self.review(report)
        self.assertEqual(self.run.wait_reason,'final_confirmation')

    def test_old_issues_cannot_disappear_and_revision_limit(self):
        self.draft()
        for turn in range(3):
            report=self.report('revision_required')
            report['issues']=[{'issue_id':'unsupported','severity':'major','state':'open'}]
            if turn:
                report['previous_issue_results']=[{'issue_id':'unsupported','result':'unresolved'}]
            self.review(report)
            if turn < 2:
                self.command('draft',content={'body':f'修改稿 {turn}'})
                self.assert_code('MODEL_OUTPUT_INVALID',lambda:self.review(self.report()))
        self.assertEqual(self.run.wait_reason,'revision_limit')
        self.assertEqual(self.run.iteration,2)

    def test_failed_gate_not_overridden_by_approved(self):
        self.draft()
        gates={k:True for k in CONTRACT['review_policy']['required_gates']}
        gates['references_valid']=False
        self.assert_code('REVIEW_GATE_FAILED',lambda:self.review(gates=gates))

    def test_concurrent_budget_reservations_cannot_overspend(self):
        self.command('start')
        def reserve(call):
            try:
                self.store.reserve(self.run.run_id,'alice',call,PARAMETERS['run_tokens_max']//2+1)
                return 'ok'
            except DomainError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            result=list(pool.map(reserve,['a','b']))
        self.assertCountEqual(result,['ok','BUDGET_EXCEEDED'])

    def test_unknown_usage_stays_reserved_and_settlement_is_idempotent(self):
        self.command('start')
        rid=self.run.run_id
        self.store.reserve(rid,'alice','a',PARAMETERS['run_tokens_max']-10000)
        self.store.settle(rid,'alice','a',None)
        self.assert_code('BUDGET_EXCEEDED',lambda:self.store.reserve(rid,'alice','b',15000))
        self.store.settle(rid,'alice','a',1000)
        self.store.settle(rid,'alice','a',1000)
        self.store.reserve(rid,'alice','b',15000)
        self.assert_code('IDEMPOTENCY_CONFLICT',lambda:self.store.settle(rid,'alice','a',999))
        self.assert_code('INVALID_INPUT',lambda:self.store.reserve(rid,'alice','c',True))

    def test_branch_retry_limit_and_terminal_failure(self):
        self.command('start')
        for attempt in range(3):
            self.command('branch',agent='research',snapshot_id='snapshot-1',outcome='retryable_error')
            if attempt < 2:
                self.assertEqual(self.run.run_status,'RETRY_WAIT')
                self.command('retry'); self.command('start')
        self.assertEqual(self.run.run_status,'FAILED')
        self.assert_code('INVALID_TRANSITION',lambda:self.command('retry'))

    def test_model_attempt_limit_counts_settled_calls(self):
        self.command('start')
        for call in range(16):
            self.store.reserve(self.run.run_id,'alice',str(call),10)
            self.store.settle(self.run.run_id,'alice',str(call),0)
        self.assert_code('BUDGET_EXCEEDED',lambda:self.store.reserve(self.run.run_id,'alice','17',10))

    def test_permissions_and_legacy_import(self):
        tool_allowed('audience','compute_content_metrics',['compute_content_metrics'],'alice','alice')
        self.assert_code('TOOL_FORBIDDEN',lambda:tool_allowed('content','export_bundle',['export_bundle'],'alice','alice'))
        self.assert_code('TOOL_DISABLED',lambda:tool_allowed('research','fetch_source_text',['fetch_source_text'],'alice','alice'))
        original={'status':'completed','draft':{'body':'旧稿'}}
        mapped=legacy_candidate(original)
        self.assertEqual(mapped['status'],'needs_review')
        self.assertFalse(mapped['accepted'])
        mapped['legacy_candidate']['draft']['body']='修改副本'
        self.assertEqual(original['draft']['body'],'旧稿')

if __name__=='__main__':
    unittest.main()
