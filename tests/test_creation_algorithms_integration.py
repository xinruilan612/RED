"""Offline fixture integration only; no real model, network or quality evidence."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from backend.contracts import DomainError
from backend.creation_algorithms import refresh
from backend.demo import validate_brief
from backend.live import messages_for, normalize, schema
from backend.provider import Config
from backend.service import Service
from backend.store import Store
from backend.worker import Worker
from test_live_provider import FixtureModel

FACT = '虚构测试设备A1水箱容量4L。'
SAMPLE = '这是专门用于测试的参考全文标记，不是真实用户文章。先说困惑，然后分析参数，最后给购买建议。'


class AlgorithmFixture(FixtureModel):
    def complete(self, messages):
        value, tokens = super().complete(messages)
        stage = self.calls[-1]
        if stage == 'audience':
            value['reader_questions'] = [{'id':'model-id','question':'水箱容量是多少？','priority':'high'}]
        if stage == 'research':
            value.update(facts=[{'source_id':'user-material','quote':FACT}], core_gap=True,
                         gaps=['产品版本还未提供'], missing_facts=[{'id':'gap-model','field':'product_version',
                         'question':'产品具体版本是什么？','priority':'high','blocks':['r1']}])
        if stage == 'strategy':
            value['content_modules'] = [{'id':'module-model','title':'容量说明','covers':['r1'],
                                         'source_id':'user-material','quote':FACT,'length':80}]
        return value, tokens


class CreationAlgorithmsIntegration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name)/'fixture.sqlite')
        self.model = AlgorithmFixture()
        self.service = Service(self.store, Config('fixture-key-never-sent'), self.model)
        self.owner = 'fixture-owner'
        no_network = patch('socket.create_connection', side_effect=AssertionError('Fixture test forbids network'))
        no_network.start()
        self.addCleanup(no_network.stop)

    def create(self, **extra):
        data = dict(topic='虚构测试设备介绍',audience='虚构读者',tone='清楚',material=FACT,
                    mode='live',allow_hypothesis=False,web_research={'enabled':False,'queries':[]},
                    knowledge={'enabled':False,'automatic_references':False})
        data.update(extra)
        result = self.service.create(self.owner,data)
        self.run_id = result['run_id']
        return self.store.get(self.run_id,self.owner)

    def command(self, action, payload=None, owner=None, version=None):
        run = self.store.get(self.run_id,self.owner)
        return self.service.action(owner or self.owner,self.run_id,dict(action=action,
            version=run.status_version if version is None else version,key=str(uuid4()),payload=payload or {}))

    def start(self):
        run = self.store.get(self.run_id,self.owner)
        self.service.background(self.owner,self.run_id,dict(action='start',version=run.status_version,key=str(uuid4())))
        self.assertTrue(Worker(self.service).once())
        return self.store.get(self.run_id,self.owner)

    def prepared(self):
        run = self.create()
        for stage in ('audience','research'):
            value,_ = self.model.complete(messages_for(run,stage)[0])
            run.branches[stage] = {'snapshot_id':run.snapshot_id,'data':normalize(run,stage,value)}
        value,_ = self.model.complete(messages_for(run,'strategy')[0])
        run.artifacts.append({'stage':'strategy','snapshot_id':run.snapshot_id,'value':normalize(run,'strategy',value)})
        refresh(run)
        return run

    def test_new_defaults_are_explicit_and_historical_tasks_do_not_opt_in(self):
        run = self.create()
        self.assertEqual(run.context['algorithm_options'],{'enabled':True,'ask_questions':False})
        old = self.store.create('historical-fixture-owner','historical',validate_brief(dict(topic='旧测试任务',audience='读者',tone='清楚',material=FACT)))
        old.branches = {'audience':{'data':{'sample_size':0}},'research':{'data':{'core_gap':False}}}
        refresh(old)
        self.assertNotIn('algorithm_state',old.context)
        self.assertNotIn('reader_questions',normalize(old,'audience',schema('audience')|{'reader_questions':[{'question':'旧任务不启用'}]}))

    def test_service_option_validation_and_switch_off(self):
        run = self.create(algorithm_options={'enabled':False,'ask_questions':True})
        self.assertEqual(run.context['algorithm_options'],{'enabled':False,'ask_questions':False})
        for value in ({'enabled':'yes'},{'extra':True},[]):
            with self.subTest(value=value), self.assertRaises(DomainError):self.create(algorithm_options=value)

    def test_five_experiment_arms_are_independent_in_actual_model_input(self):
        from backend.creation_algorithms import options
        arms = {'A': {'enabled': False},
                'B': {'coverage': True, 'structure': False},
                'C': {'coverage': False, 'structure': False, 'ask_questions': True},
                'D': {'coverage': False, 'structure': True},
                'E': {'coverage': True, 'structure': True, 'ask_questions': True}}
        import copy
        prepared = self.prepared()
        for arm, settings in arms.items():
            with self.subTest(arm=arm):
                run = copy.deepcopy(prepared)
                run.context['algorithm_options'] = options(settings)
                reference = {'source_id': 'sample-arm', 'text': SAMPLE, 'title': '样例',
                             'version': 1, 'evidence_role': 'expression_reference'}
                run.context['creation_retrieval']['groups']['examples'] = [reference]
                refresh(run)
                messages, _ = messages_for(run, 'body')
                payload = json.loads(messages[1]['content'])
                proposal = payload.get('creation_plan', {})
                self.assertEqual('selected_modules' in proposal, arm in ('B', 'E'))
                self.assertEqual('structure' in proposal, arm in ('D', 'E'))
                self.assertEqual(SAMPLE in json.dumps(messages, ensure_ascii=False), arm not in ('D', 'E'))
                titles, _ = messages_for(run, 'title')
                self.assertIn('16字符以内', titles[0]['content'])
                strategy, _ = messages_for(run, 'strategy')
                self.assertEqual('必须额外输出content_modules' in strategy[0]['content'], arm in ('B', 'E'))

    def test_normalize_retains_bounded_candidates_and_strategy_provenance(self):
        run = self.prepared()
        self.assertEqual(run.branches['audience']['data']['reader_questions'][0]['id'],'model-id')
        self.assertEqual(run.branches['research']['data']['missing_facts'][0]['field'],'product_version')
        state = run.context['algorithm_state']
        self.assertEqual(state['snapshot_id'],run.snapshot_id)
        self.assertEqual(state['planning']['selected_modules'][0]['source_ids'],['user-material'])
        self.assertEqual(state['planning']['selected_modules'][0]['quote'],FACT)
        self.assertLessEqual(state['planning']['used_budget'],state['planning']['budget'])

    def test_body_prompt_receives_structure_instead_of_reference_fulltext(self):
        run = self.prepared()
        reference = {'source_id':'sample-fixture','source_type':'fixture','title':'虚构参考',
                     'text':SAMPLE,'version':1,'evidence_role':'expression_reference'}
        run.context['evidence'] = [reference]
        run.context['creation_retrieval']['groups']['examples'] = [reference]
        refresh(run)
        messages, _ = messages_for(run,'body')
        rendered = json.dumps(messages,ensure_ascii=False)
        self.assertNotIn(SAMPLE,rendered)
        payload = json.loads(messages[1]['content'])
        self.assertTrue(payload['creation_plan']['structure']['slots'])
        self.assertIn(FACT,rendered)
        # Full source remains in the immutable task snapshot for review/audit.
        self.assertEqual(run.context['evidence'][0]['text'],SAMPLE)

    def test_generation_guidance_respects_each_module_switch_and_stage(self):
        import copy
        from backend.creation_algorithms import options
        original = self.prepared()
        original.drafts = [{'ref':'fixture-draft', 'content':schema('body')}]
        for coverage, structure in ((False, False), (True, False), (False, True), (True, True)):
            for stage in ('outline', 'hook', 'title', 'body', 'revise', 'research'):
                with self.subTest(coverage=coverage, structure=structure, stage=stage):
                    run = copy.deepcopy(original)
                    run.context['algorithm_options'] = options({'coverage':coverage, 'structure':structure})
                    refresh(run)
                    before = copy.deepcopy(run.context['algorithm_state'])
                    messages, _ = messages_for(run,stage)
                    instruction = messages[0]['content']
                    writing = stage != 'research'
                    self.assertEqual('不是事实白名单' in instruction, coverage and writing)
                    self.assertEqual('不是正文目标长度' in instruction, coverage and writing)
                    self.assertEqual('段落功能可合并或省略' in instruction, structure and writing)
                    # Guidance must not rewrite the optimizer, strip actual facts,
                    # or relax source grounding to fill missing evidence.
                    self.assertEqual(run.context['algorithm_state'], before)
                    self.assertIn(FACT, messages[1]['content'])
                    if coverage and writing:
                        self.assertIn('材料不足时不灌水、不补造事实', instruction)
                    if structure and writing:
                        self.assertIn('缺证据的体验或对比不能写成事实', instruction)

    def test_worker_default_flow_reaches_review_with_diagnostic_plan(self):
        self.create()
        run = self.start()
        self.assertEqual(run.run_status,'WAITING_USER')
        self.assertEqual(run.wait_reason,'final_confirmation')
        self.assertEqual(len(run.drafts),1)
        self.assertEqual(set(self.model.calls),{'audience','research','strategy','outline','hook','title','body','review'})
        self.assertTrue(run.context['algorithm_state']['planning']['selected_modules'])
        self.assertEqual(run.context['algorithm_state']['review']['draft_ref'],run.drafts[-1]['ref'])

    def test_optional_question_skip_retains_snapshot_and_never_reasks(self):
        self.create(algorithm_options={'enabled':True,'ask_questions':True})
        run = self.start()
        self.assertEqual((run.run_status,run.wait_reason),('WAITING_USER','missing_material'))
        self.assertEqual(self.model.calls.count('body'),0)
        self.assertIn('skip_questions',self.service.view(run)['allowed_actions'])
        snapshot = run.snapshot_id
        self.command('skip_questions')
        run = self.start()
        self.assertEqual(run.snapshot_id,snapshot)
        self.assertEqual(run.context['material'],FACT)
        self.assertEqual(run.context['algorithm_questions_status'],'skipped')
        self.assertEqual(run.wait_reason,'final_confirmation')
        self.assertEqual(self.model.calls.count('research'),1)

    def test_supplement_preserves_original_and_rebuilds_snapshot_only_one_question_round(self):
        self.create(algorithm_options={'enabled':True,'ask_questions':True})
        old = self.start()
        self.command('supplement',{'material':'虚构测试版本：基础版。','allow_hypothesis':False})
        updated = self.store.get(self.run_id,self.owner)
        self.assertNotEqual(old.snapshot_id,updated.snapshot_id)
        self.assertIn(FACT,updated.context['material'])
        self.assertIn('基础版',updated.context['material'])
        self.assertEqual(updated.context['algorithm_questions_status'],'answered')
        self.assertNotIn('algorithm_state',updated.context)
        run = self.start()
        self.assertEqual(run.wait_reason,'final_confirmation')
        self.assertEqual(self.model.calls.count('research'),2)
        self.assertEqual(self.model.calls.count('body'),1)

    def test_disabled_algorithms_keep_legacy_creation_flow(self):
        self.create(algorithm_options={'enabled':False})
        run = self.start()
        self.assertEqual(run.wait_reason,'final_confirmation')
        self.assertNotIn('algorithm_state',run.context)
        self.assertNotIn('reader_questions',run.branches['audience']['data'])

    def test_stale_version_and_cross_owner_cannot_resolve_questions(self):
        self.create(algorithm_options={'ask_questions':True})
        run = self.start()
        for owner,version,code in [(self.owner,run.status_version-1,'VERSION_CONFLICT'),('other-fixture-owner',run.status_version,'RESOURCE_NOT_FOUND')]:
            with self.subTest(code=code), self.assertRaises(DomainError) as caught:
                self.command('skip_questions',owner=owner,version=version)
            self.assertEqual(caught.exception.code,code)
        self.assertEqual(self.store.get(self.run_id,self.owner).context['algorithm_questions_status'],'pending')

    def test_negated_experience_and_unrelated_facts_cannot_enable_evidence_slots(self):
        run = self.prepared()
        run.context['material'] = '没有亲测记录，请不要编造体验。'
        run.branches['research']['data']['facts'] = [
            {'source_id':'user-material','quote':'没有亲测记录，请不要编造体验。'}]
        refresh(run)
        fields = run.context['algorithm_state']['structure']['available_fields']
        self.assertNotIn('firsthand_record',fields)
        self.assertNotIn('product_specs',fields)
        self.assertNotIn('comparison_specs',fields)

    def test_diagnostics_do_not_bind_old_draft_to_new_snapshot(self):
        run = self.prepared()
        run.drafts.append({'ref':'old@1','snapshot_id':'old-snapshot','content_hash':'old',
                           'content':{'body':'旧稿件'}})
        refresh(run)
        self.assertNotIn('review',run.context['algorithm_state'])

    def test_coverage_cannot_count_height_as_installation_comparison_or_vent_position(self):
        from backend.creation_algorithms import coverage_evidence_matches
        quote = 'A1普通版机身高度35厘米。'
        self.assertFalse(coverage_evidence_matches('A1普通版散热口位置在哪？',quote))
        self.assertFalse(coverage_evidence_matches('A1普通版和上下水版高度一样吗？',quote))
        self.assertFalse(coverage_evidence_matches('柜体净高38厘米能装A1普通版吗？',quote))
        self.assertFalse(coverage_evidence_matches('A1普通版4L水箱对应多大使用面积、每天加水几次？','A1普通版水箱容量4L。'))
        self.assertFalse(coverage_evidence_matches('A1机身35厘米，要求柜体40厘米，多出的5厘米留给什么？','A1机身35厘米，柜体净高至少40厘米。'))
        self.assertTrue(coverage_evidence_matches('A1普通版机身高度是多少？',quote))

    def test_pending_questions_cannot_be_bypassed_by_background_start(self):
        self.create(algorithm_options={'enabled':True,'ask_questions':True})
        run = self.start()
        with self.assertRaises(DomainError):
            self.service.background(self.owner,self.run_id,dict(action='start',version=run.status_version,key=str(uuid4())))
        self.assertEqual(self.store.get(self.run_id,self.owner).run_status,'WAITING_USER')


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'requires actual isolated PostgreSQL schema')
class PostgresCreationAlgorithmsIntegration(CreationAlgorithmsIntegration):
    def setUp(self):
        super().setUp()
        import psycopg
        base = os.environ['TEST_DATABASE_URL']
        schema = 'youji_algorithms_'+uuid4().hex
        with psycopg.connect(base,autocommit=True) as db:
            db.execute('CREATE SCHEMA '+schema)
        def drop():
            with psycopg.connect(base,autocommit=True) as db:
                db.execute('DROP SCHEMA '+schema+' CASCADE')
        self.addCleanup(drop)
        self.store = Store(base+('&' if '?' in base else '?')+'options=-csearch_path%3D'+schema)
        self.service = Service(self.store,Config('fixture-key-never-sent'),self.model)
