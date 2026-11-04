"""Length recovery uses existing text only; no paid model calls."""
import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent))
from backend.live import bounded_title_candidates, normalize
from backend.contracts import DomainError


def task(classified=True, platform='xiaohongshu'):
    context={'operations':{'platform':platform}}
    if classified:context['creation_classification']={'domains':['digital'],'channel':'xiaohongshu','format':'note'}
    return SimpleNamespace(context=context)


def response(candidates=None,selected=None):
    values=candidates or ['合法标题一','合法标题二','合法标题三','合法标题四','合法标题五']
    return {'candidates':values,'reasons':['第%d项理由'%i for i in range(len(values))],
            'selected':selected or values[0],'note':'原始选择说明'}


class TitleFilterTests(unittest.TestCase):
    def test_unselected_overlong_is_removed_without_changing_selected_or_raw(self):
        raw=response(['合法标题一','合法标题二','合法标题三','长'*21,'合法标题五'])
        before=copy.deepcopy(raw)
        value,log=bounded_title_candidates(task(),raw)
        self.assertEqual(value['selected'],raw['selected'])
        self.assertEqual(value['candidates'],[raw['candidates'][i] for i in [0,1,2,4]])
        self.assertEqual(value['reasons'],[raw['reasons'][i] for i in [0,1,2,4]])
        self.assertEqual(log['rejected_indices'],[3]);self.assertEqual(log['rejected_lengths'],[21])
        self.assertEqual(raw,before)
        self.assertEqual(normalize(task(),'title',raw),value)

    def test_invalid_selected_uses_first_existing_compliant_candidate(self):
        raw=response(['长'*21,'短标题','另一个标题','备选三','备选四'])
        value,log=bounded_title_candidates(task(),raw)
        self.assertEqual(value['selected'],'短标题')
        self.assertEqual(log['original_selected'],'长'*21)
        self.assertEqual(log['used_selected'],'短标题')
        self.assertIn('第1项理由',value['note'])
        self.assertNotIn('原始选择说明',value['note'])
        self.assertEqual(normalize(task(),'title',raw),value)

    def test_all_overlong_rejected_and_no_text_truncation(self):
        raw=response(['长'*21+str(i) for i in range(5)])
        self.assertIsNone(bounded_title_candidates(task(),raw)[1])
        with self.assertRaises(DomainError):normalize(task(),'title',raw)

    def test_surplus_keeps_first_four_and_selected(self):
        raw=response(['题%d'%i for i in range(8)],'题7')
        value,log=bounded_title_candidates(task(),raw)
        self.assertEqual(log['kept_indices'],[0,1,2,3,7])
        self.assertEqual(value['selected'],'题7')
        self.assertEqual(value['reasons'],['第%d项理由'%i for i in [0,1,2,3,7]])

    def test_strict_schema_and_legacy_scope_not_relaxed(self):
        raw=response(['合法','长'*21,'备选二','备选三','备选四'])
        with self.assertRaises(DomainError):normalize(task(False),'title',raw)
        self.assertEqual(normalize(task(True,'douyin'),'title',raw),raw)
        invalid=[dict(raw,reasons=raw['reasons'][:-1]),dict(raw,candidates=['相同']*5),
                 dict(raw,selected='不存在'),response(['题%d'%i for i in range(4)]),
                 response(['题%d'%i for i in range(11)]),response(['长'*201,'二','三','四','五']),
                 dict(raw,reasons=['']*5)]
        for value in invalid:
            with self.subTest(value=value),self.assertRaises(DomainError):normalize(task(),'title',value)

    def test_unicode_codepoints_and_exact_limit(self):
        raw=response(['😀'*20,'😀'*21,'边界二','边界三','边界四'])
        value,log=bounded_title_candidates(task(),raw)
        self.assertIn('😀'*20,value['candidates']);self.assertNotIn('😀'*21,value['candidates'])
        self.assertEqual(log['rejected_lengths'],[21])
        self.assertEqual(normalize(task(),'title',raw)['selected'],'😀'*20)


class TitleFilterWorkerTests(unittest.TestCase):
    def test_worker_reuses_received_raw_response_without_extra_title_fee(self):
        # Reuse the established durable-runtime harness without inheriting and
        # accidentally rerunning all its unrelated integration cases.
        from test_durable_runtime import DurableTests
        from backend.worker import Worker
        harness=DurableTests(methodName='test_received_six_titles_replays_without_extra_call_and_keeps_raw_response')
        harness.setUp()
        self.addCleanup(harness.tearDown)
        from dataclasses import asdict
        with harness.store.connect() as db:
            run=harness.store._get(db,harness.run_id,harness.owner)
            run.context['operations']={'platform':'xiaohongshu'}
            db.execute('UPDATE runs SET payload=? WHERE id=?',(json.dumps(asdict(run),ensure_ascii=False),harness.run_id))
        raw=response(['长'*21,'参数核对清单','已有条件先核对','使用边界说明','购买前检查'])
        original=copy.deepcopy(raw)
        base=harness.model.complete
        def received(messages):
            value,tokens=base(messages)
            stage=harness.model.calls[-1]
            if stage=='title':value=copy.deepcopy(raw)
            if stage=='body':value['selected_title']=json.loads(messages[1]['content'])['upstream']['title']['selected']
            return value,tokens
        harness.model.complete=received
        # First persist exactly the same invalid response under the old policy.
        with patch('backend.live.bounded_title_candidates',side_effect=lambda run,value:(value,None)):
            harness.start();Worker(harness.service).once()
        self.assertEqual(harness.job()['status'],'blocked')
        self.assertEqual(harness.model.calls.count('title'),1)
        with harness.store.connect() as db:
            before=db.execute("SELECT id,response_json,actual FROM live_calls WHERE run_id=? AND stage='title'",(harness.run_id,)).fetchone()
        harness.start();Worker(harness.service).once()
        run=harness.run_value()
        self.assertEqual(run.wait_reason,'final_confirmation',harness.job())
        self.assertEqual(harness.model.calls.count('title'),1)
        title=next(node for node in run.node_runs if node['stage']=='title')
        self.assertEqual(title['output']['selected'],'参数核对清单')
        self.assertEqual(title['output_normalizations'][0]['rejected_indices'],[0])
        with harness.store.connect() as db:
            after=db.execute("SELECT id,response_json,actual FROM live_calls WHERE run_id=? AND stage='title'",(harness.run_id,)).fetchall()
        self.assertEqual(len(after),1)
        self.assertEqual(tuple(before),tuple(after[0]))
        self.assertEqual(json.loads(after[0][1]),original)
        self.assertEqual(raw,original)


if __name__=='__main__':unittest.main()
