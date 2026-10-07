"""Domain acceptance: isolation, immutable comparisons, exact patches and lineage."""
import copy
import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from backend.accounts import PROFILE_FIELDS
from backend.contracts import DomainError
from backend.knowledge import Knowledge
from backend.migrations import upgrade
from backend.operations import Operations
from backend.store import Store
from backend.windtunnel import (Windtunnel, apply_stage, conditions, current_report, draft,
                                citations, edit_spans, evidence_passages, reading_passages, material_hash, messages_for, normalize, simulate, stage_sources)
from backend.workflow import digest


class WindtunnelDomainTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / 'domain.sqlite')
        upgrade(self.store)
        self.ops = Operations(self.store)
        self.knowledge = Knowledge(self.store)
        self.wind = Windtunnel(self.store, self.ops, self.knowledge)
        self.owner = 'alice'
        self.account = self.account_for(self.owner)

    def tearDown(self):
        self.temp.cleanup()

    def account_for(self, owner, name='工具教程'):
        state = self.ops.read(owner)
        payload = dict(id='', name=name, platform='xiaohongshu', profile={**{k: '' for k in PROFILE_FIELDS}, 'weekly_frequency': 3})
        state = self.ops.command(owner, dict(action='save_account', payload=payload, version=state['version'], key=str(uuid4())))
        return state['accounts'][-1]['id']

    def create(self, **overrides):
        return self.wind.create(self.owner, {**dict(account_id=self.account, title='工具入门', text='打开工具。点击导出。',
                                                scene='没有经验的学生读者', materials=[{'text': '工具版本为 1.2，导出后保存至下载目录。', 'title': '工具官方说明'}]), **overrides})

    def persist(self, run):
        with self.store.connect() as db:
            db.execute('UPDATE runs SET payload=? WHERE id=?', (json.dumps(asdict(run), ensure_ascii=False), run.run_id))
        return run

    def step(self, run, value=None):
        run.run_status = 'RUNNING'
        stage = run.current_stage
        apply_stage(run, stage, normalize(run, stage, simulate(run, stage) if value is None else value))
        run.status_version += 1
        return self.persist(run)

    def action(self, run, action, **payload):
        return self.wind.action(self.owner, run.run_id, dict(action=action, version=run.status_version, key=str(uuid4()), payload=payload))

    def confirmed(self, **overrides):
        run = self.step(self.create(**overrides))
        cs = conditions(run)
        return self.action(run, 'confirm_conditions', condition_set_id=cs['id'], condition_hash=cs['hash'])

    def report(self, **overrides):
        return self.step(self.step(self.confirmed(**overrides)))

    def grounded_patch(self, run):
        text = draft(run)['text']
        source = next(s for s in run.windtunnel['sources'] if s['kind'] == 'material')
        return {'patches': [dict(start=len(text), end=len(text), original='', replacement='\n\n工具版本为 1.2，导出后保存至下载目录。',
                                condition_ids=[run.windtunnel['patch_condition_ids'][0]], reason='补全工具版本和保存目录',
                                citations=[dict(source_id=source['id'], quote='工具版本为 1.2，导出后保存至下载目录。')])]}

    def test_reading_whitelist_excludes_material_feedback_old_answers_and_profile(self):
        run = self.confirmed(feedback=[dict(text='秘密答案：1.2版本', origin='2026-09 试读', provenance='pilot_feedback', permission=True)])
        run.context['operations'] = {'profile': {'secret': 'PROFILE_SECRET'}}
        run.windtunnel['reports'] = [{'results': ['REPORT_SECRET']}]
        run.windtunnel['reading'] = [{'answer': 'OLD_READING_SECRET'}]
        _, inputs = messages_for(run, 'wt_read')
        serialized = json.dumps(inputs, ensure_ascii=False)
        self.assertEqual(set(inputs), {'scene', 'draft', 'conditions', 'reading_passages'})
        for forbidden in ('工具官方说明', 'PROFILE_SECRET', 'REPORT_SECRET', 'OLD_READING_SECRET', 'materials', 'source_ids'):
            self.assertNotIn(forbidden, serialized)
        self.assertEqual([s['kind'] for s in stage_sources(run, 'wt_read')], ['draft'])

    def test_exploration_failures_remain_rejected_with_explicit_prompt_rules(self):
        run = self.confirmed()
        messages, _ = messages_for(run, 'wt_read')
        self.assertIn('禁止拼接', messages[0]['content'])
        reading = simulate(run, 'wt_read')
        reading['results'][0].update(status='pass', answer='答案', excerpt='打开工具。导出。')
        with self.assertRaises(DomainError):
            normalize(run, 'wt_read', reading)
        run = self.step(run)
        messages, _ = messages_for(run, 'wt_verify')
        self.assertIn('本条必须输出unclear', messages[0]['content'])
        verify = simulate(run, 'wt_verify')
        verify['results'][0]['status'] = 'insufficient'
        with self.assertRaises(DomainError):
            normalize(run, 'wt_verify', verify)

    def test_patch_model_only_receives_author_selected_problem_ids(self):
        run = self.report()
        report = current_report(run)
        selected = report['results'][0]['condition_id']
        excluded = {r['condition_id'] for r in report['results'][1:]}
        run = self.action(run, 'propose_patch', condition_ids=[selected])
        _, inputs = messages_for(run, 'wt_patch')
        self.assertEqual({c['id'] for c in inputs['conditions']}, {selected})
        self.assertEqual({r['condition_id'] for r in inputs['report']}, {selected})
        serialized = json.dumps(inputs)
        for identity in excluded:
            self.assertNotIn(identity, serialized)

    def test_span_boundaries_use_unicode_offsets_and_keep_legacy_exact_guard(self):
        text = '甲🙂乙\n\n第二段原文。'
        run = self.wind.create(self.owner, dict(account_id=self.account, title='说明', text=text,
                                               materials=[dict(text='第二段应解释操作步骤。')]))
        run = self.step(run)
        cs = conditions(run)
        run = self.action(run, 'confirm_conditions', condition_set_id=cs['id'], condition_hash=cs['hash'])
        run = self.step(self.step(run))
        cid = current_report(run)['results'][0]['condition_id']
        run = self.action(run, 'propose_patch', condition_ids=[cid])
        _, inputs = messages_for(run, 'wt_patch')
        self.assertEqual(inputs['edit_spans'][1]['start'], 3)
        self.assertEqual(inputs['edit_spans'][-1]['start'], len(text))
        patch = dict(start=3, end=3, original='', replacement='\n具体步骤说明。', condition_ids=[cid],
                     reason='补出步骤', citations=[dict(source_id=run.windtunnel['sources'][0]['id'], quote='解释操作步骤')])
        self.assertEqual(normalize(run, 'wt_patch', dict(patches=[patch]))['patches'][0]['start'], 3)
        patch.update(start=4, end=5, original='乙')
        with self.assertRaises(DomainError):
            normalize(run, 'wt_patch', dict(patches=[patch]))

    def test_cross_owner_and_account_import_and_knowledge_denied(self):
        from backend.demo import validate_brief
        bob_account = self.account_for('bob')
        foreign = self.store.create('bob', 'old-snapshot', validate_brief(dict(topic='示例', audience='读者', tone='清楚')))
        foreign.context['operations'] = {'account_id': bob_account}
        foreign.drafts = [dict(ref='version-one', content={'selected_title': '别人的稿', 'body': '不能导入'}, content_hash='abc')]
        self.persist(foreign)
        with self.assertRaises(DomainError):
            self.wind.create(self.owner, dict(account_id=self.account, **{'import': {'run_id': foreign.run_id, 'draft_ref': 'version-one'}}))
        doc = self.knowledge.save('bob', dict(account_id=bob_account, title='秘密', text='私人原文'))
        with self.assertRaises(DomainError):
            self.create(knowledge=[{'document_id': doc['id'], 'version': doc['version']}])
        with self.assertRaises(DomainError):
            self.wind.checklists('bob', self.account)

    def test_import_exact_draft_version_is_a_copy_without_approval(self):
        from backend.demo import validate_brief
        source = self.store.create(self.owner, 'snapshot', validate_brief(dict(topic='工具', audience='学生', tone='清楚')))
        source.context['operations'] = {'account_id': self.account}
        source.drafts = [dict(ref='v1', content={'selected_title': '旧稿', 'body': '旧正文', 'cta': '附加承诺也需检查', 'tags': ['#工具']}, content_hash='oldhash'),
                         dict(ref='v2', content={'selected_title': '新稿', 'body': '新正文'}, content_hash='newhash')]
        source.accepted_ref = 'v2'
        self.persist(source)
        run = self.wind.create(self.owner, dict(account_id=self.account, **{'import': dict(run_id=source.run_id, draft_ref='v1')}))
        self.assertEqual(draft(run)['text'], '旧正文\n\n附加承诺也需检查\n\n#工具')
        self.assertEqual(draft(run)['source']['draft_ref'], 'v1')
        self.assertIsNone(run.accepted_ref)
        source.drafts[0]['content']['body'] = '源记录变化'
        self.persist(source)
        self.assertEqual(draft(self.store.get(run.run_id, self.owner))['text'], '旧正文\n\n附加承诺也需检查\n\n#工具')

    def test_feedback_permission_and_author_provenance_cannot_be_laundered(self):
        with self.assertRaises(DomainError):
            self.create(feedback=[dict(text='一个问题', origin='真实评论', permission=False)])
        run = self.create(feedback=[dict(text='只是作者猜想', origin='作者设定', permission=True)])
        source_id = run.windtunnel['sources'][-1]['id']
        authored = next(s for s in run.windtunnel['sources'] if s['kind'] == 'feedback')
        with self.assertRaises(DomainError):
            normalize(run, 'wt_conditions', {'conditions': [dict(question='假设？', origin='feedback', source_ids=[authored['id']])]})
        self.assertTrue(all(c['origin'] == 'author' for c in simulate(run, 'wt_conditions')['conditions']))

    def test_incomplete_results_bad_quotes_and_missing_basis_are_model_errors(self):
        run = self.confirmed()
        reading = simulate(run, 'wt_read')
        with self.assertRaises(DomainError):
            normalize(run, 'wt_read', {'results': reading['results'][:-1]})
        reading['results'][0].update(status='pass', answer='幻觉答案', excerpt='正文不存在')
        with self.assertRaises(DomainError):
            normalize(run, 'wt_read', reading)
        run = self.step(run)
        verify = simulate(run, 'wt_verify')
        verify['results'][0].update(status='pass', citations=[])
        with self.assertRaises(DomainError):
            normalize(run, 'wt_verify', verify)
        self.assertEqual(run.windtunnel['reports'], [])

    def test_four_outcomes_need_exact_fixed_conditions_and_material_quotes(self):
        run = self.step(self.create())
        values = [dict(id=str(i), question='问题' + str(i), scene='教程', source_ids=[], origin='author') for i in range(4)]
        run = self.action(run, 'edit_conditions', conditions=values)
        cs = conditions(run)
        run = self.action(run, 'confirm_conditions', condition_set_id=cs['id'], condition_hash=cs['hash'])
        read = {'results': [dict(condition_id=str(i), status='unclear' if i == 1 else 'pass', answer='' if i == 1 else '打开工具', excerpt='' if i == 1 else '打开工具', reason='逐字定位') for i in range(4)]}
        run = self.step(run, read)
        source = next(s for s in run.windtunnel['sources'] if s['kind'] == 'material')
        verify = {'results': [dict(condition_id=str(i), status=status, reason='基于材料核对', citations=[{'source_id': source['id'], 'quote': '工具版本为 1.2'}] if status in ('pass', 'unsupported') else []) for i, status in enumerate(('pass', 'unclear', 'unsupported', 'insufficient'))], 'new_issues': []}
        run = self.step(run, verify)
        self.assertEqual([r['status'] for r in current_report(run)['results']], ['pass', 'unclear', 'unsupported', 'insufficient'])

    def test_recheck_keeps_conditions_and_cannot_finish_or_export_old_batch(self):
        run = self.report()
        old = copy.deepcopy(current_report(run))
        cs = copy.deepcopy(conditions(run))
        run = self.action(run, 'recheck', condition_set_id=cs['id'])
        self.assertEqual(cs, conditions(run))
        with self.assertRaises(DomainError):
            self.action(run, 'finish')
        with self.assertRaises(DomainError):
            self.wind.export(run)
        run = self.step(self.step(run))
        new = current_report(run)
        self.assertNotEqual(old['batch_id'], new['batch_id'])
        self.assertEqual(old, run.windtunnel['reports'][0])
        self.assertEqual(old['condition_hash'], new['condition_hash'])

    def test_same_text_condition_new_version_invalidates_old_report(self):
        run = self.report()
        before = copy.deepcopy(conditions(run))
        run = self.action(run, 'edit_conditions', conditions=before['conditions'])
        self.assertEqual(before['hash'], conditions(run)['hash'])
        self.assertNotEqual(before['id'], conditions(run)['id'])
        with self.assertRaises(DomainError):
            current_report(run)
        with self.assertRaises(DomainError):
            self.action(run, 'recheck', condition_set_id=before['id'])

    def test_edit_before_condition_confirmation_preserves_confirmation_path(self):
        run = self.step(self.create())
        d = draft(run)
        run = self.action(run, 'edit_draft', title=d['title'], text=d['text'] + '\n\n补充说明。', base_hash=d['hash'])
        self.assertEqual(run.wait_reason, 'wt_confirm_conditions')
        run = self.action(run, 'update_materials', base_material_hash=material_hash(run), materials=[{'text': '材料修正'}])
        self.assertEqual(run.wait_reason, 'wt_confirm_conditions')
        cs = conditions(run)
        run = self.action(run, 'confirm_conditions', condition_set_id=cs['id'], condition_hash=cs['hash'])
        self.assertEqual(run.current_stage, 'wt_read')
        self.assertEqual(run.run_status, 'QUEUED')

    def test_malformed_model_ids_and_public_references_are_domain_errors(self):
        with self.assertRaises(DomainError):
            self.create(knowledge=[{'document_id': {}, 'version': 1}])
        run = self.create()
        with self.assertRaises(DomainError):
            self.wind.export(run)
        run = self.step(run)
        cs = conditions(run)
        run = self.action(run, 'confirm_conditions', condition_set_id=cs['id'], condition_hash=cs['hash'])
        output = simulate(run, 'wt_read')
        output['results'][0]['condition_id'] = {}
        with self.assertRaises(DomainError):
            normalize(run, 'wt_read', output)

    def test_patch_is_explicit_partial_hash_bound_and_idempotent(self):
        run = self.report()
        original = copy.deepcopy(draft(run))
        run = self.action(run, 'propose_patch', condition_ids=[conditions(run)['conditions'][0]['id']])
        run = self.step(run, self.grounded_patch(run))
        patch = run.windtunnel['patches'][-1]
        self.assertEqual(original, draft(run))
        item = patch['items'][0]
        command = dict(action='apply_patch', version=run.status_version, key='once', payload=dict(patch_id=patch['id'], item_ids=[item['id']], base_hash=original['hash']))
        changed = self.wind.action(self.owner, run.run_id, command)
        again = self.wind.action(self.owner, run.run_id, command)
        self.assertEqual(asdict(changed), asdict(again))
        self.assertEqual(changed.windtunnel['drafts'][0], original)
        self.assertEqual(draft(changed)['text'], original['text'] + item['replacement'])
        self.assertEqual(changed.wait_reason, 'wt_recheck')
        with self.assertRaises(DomainError):
            self.wind.export(changed)
        with self.assertRaises(DomainError):
            self.action(changed, 'apply_patch', patch_id=patch['id'], item_ids=[item['id']], base_hash=original['hash'])

    def test_patch_refuses_overlaps_and_unsupported_new_facts(self):
        run = self.report()
        run = self.action(run, 'propose_patch', condition_ids=[conditions(run)['conditions'][0]['id']])
        output = self.grounded_patch(run)
        output['patches'].append(copy.deepcopy(output['patches'][0]))
        with self.assertRaises(DomainError):
            normalize(run, 'wt_patch', output)
        output = self.grounded_patch(run)
        output['patches'][0]['citations'] = []
        output['patches'][0]['replacement'] = '保证导出成功，永久免费。'
        with self.assertRaises(DomainError):
            normalize(run, 'wt_patch', output)
        output['patches'][0]['replacement'] = '本品免烫且永久免费。待核实'
        with self.assertRaises(DomainError):
            normalize(run, 'wt_patch', output)

    def test_placeholder_and_question_echo_are_rejected_even_with_citations(self):
        run = self.report()
        selected = conditions(run)['conditions'][0]
        run = self.action(run, 'propose_patch', condition_ids=[selected['id']])
        for replacement in ('\n\n待补充并核实：' + selected['question'], selected['question']):
            for with_citations in (False, True):
                output = self.grounded_patch(run)
                output['patches'][0]['replacement'] = replacement
                if not with_citations:
                    output['patches'][0]['citations'] = []
                with self.assertRaises(DomainError):
                    normalize(run, 'wt_patch', output)

    def test_material_explanation_replaces_exact_local_span_and_requires_recheck(self):
        run = self.report()
        before = copy.deepcopy(draft(run))
        run = self.action(run, 'propose_patch', condition_ids=[conditions(run)['conditions'][0]['id']])
        output = self.grounded_patch(run)
        item = output['patches'][0]
        anchor = '点击导出。'
        item.update(start=before['text'].index(anchor), end=before['text'].index(anchor) + len(anchor),
                    original=anchor, replacement='在 1.2 版本点击导出，文件保存至下载目录。')
        wrong_offset = copy.deepcopy(output)
        wrong_offset['patches'][0]['start'] += 1
        with self.assertRaises(DomainError):
            normalize(run, 'wt_patch', wrong_offset)
        run = self.step(run, output)
        proposal = run.windtunnel['patches'][-1]
        run = self.action(run, 'apply_patch', patch_id=proposal['id'], item_ids=[proposal['items'][0]['id']], base_hash=before['hash'])
        self.assertEqual(draft(run)['text'], '打开工具。在 1.2 版本点击导出，文件保存至下载目录。')
        self.assertEqual(run.wait_reason, 'wt_recheck')
        self.assertEqual(run.windtunnel['drafts'][0], before)
        with self.assertRaises(DomainError):
            self.wind.export(run)

    def test_no_material_returns_empty_patch_and_preserves_unresolved_report(self):
        run = self.report(materials=[])
        before = copy.deepcopy(draft(run))
        report = copy.deepcopy(current_report(run))
        run = self.action(run, 'propose_patch', condition_ids=[conditions(run)['conditions'][0]['id']])
        messages, data = messages_for(run, 'wt_patch')
        self.assertEqual(data['materials'], [])
        self.assertIn('材料不足以提供答案时返回', messages[0]['content'])
        run = self.step(run, {'patches': []})
        self.assertEqual(draft(run), before)
        self.assertEqual(current_report(run), report)
        self.assertEqual(run.windtunnel['patches'][-1]['items'], [])
        self.assertNotIn('apply_patch', self.wind.view(run)['allowed_actions'])

    def test_span_ids_compile_unicode_and_distinguish_duplicate_paragraphs(self):
        text = '🙂重复段。\n\n🙂重复段。\n\n末尾。'
        spans = edit_spans(text)
        replacements = [s for s in spans if s['kind'] == 'replace']
        self.assertNotEqual(replacements[0]['span_id'], replacements[1]['span_id'])
        self.assertEqual(replacements[1]['start'], len('🙂重复段。\n\n'))
        for target in spans:
            self.assertEqual(text[target['start']:target['end']], target['original'])
        self.assertEqual(spans[-1]['start'], len(text))
        run = self.report(text=text)
        run = self.action(run, 'propose_patch', condition_ids=[conditions(run)['conditions'][0]['id']])
        output = self.grounded_patch(run)
        item = output['patches'][0]
        item.pop('start'); item.pop('end')
        item.update(span_id=replacements[1]['span_id'], original=replacements[1]['original'])
        compiled = normalize(run, 'wt_patch', output)['patches'][0]
        self.assertEqual((compiled['start'], compiled['end']), (replacements[1]['start'], replacements[1]['end']))
        self.assertNotIn('span_id', compiled)
        for bad in ('unknown', edit_spans(text + '!')[0]['span_id']):
            invalid = copy.deepcopy(output)
            invalid['patches'][0]['span_id'] = bad
            with self.assertRaises(DomainError): normalize(run, 'wt_patch', invalid)
        output['patches'][0]['original'] = '重复段。'
        with self.assertRaises(DomainError): normalize(run, 'wt_patch', output)

    def test_end_span_inserts_grounded_text_without_model_offsets(self):
        run = self.report(text='🙂简明教程。')
        run = self.action(run, 'propose_patch', condition_ids=[conditions(run)['conditions'][0]['id']])
        messages, data = messages_for(run, 'wt_patch')
        self.assertIn('span_id', messages[0]['content'])
        output = self.grounded_patch(run)
        item = output['patches'][0]
        item.pop('start'); item.pop('end')
        item['span_id'] = data['edit_spans'][-1]['span_id']
        normalized = normalize(run, 'wt_patch', output)['patches'][0]
        self.assertEqual(normalized['start'], len('🙂简明教程。'))
        self.assertIn('下载目录', normalized['replacement'])
        self.assertEqual(len(edit_spans('\n\n'.join(['段'] * 100))), 121)
        self.assertEqual(edit_spans('\n\n'.join(['段'] * 100))[-1]['start'], len('\n\n'.join(['段'] * 100)))

    def test_evidence_ids_preserve_unicode_whitespace_and_duplicate_identity(self):
        sources = [dict(id='material-1', kind='material', text='🙂代码\n  缩进\n\n🙂代码\n  缩进'),
                   dict(id='feedback-1', kind='feedback', text='不能作为材料引用')]
        passages = evidence_passages(sources)
        self.assertEqual(len(passages), 2)
        self.assertNotEqual(passages[0]['evidence_id'], passages[1]['evidence_id'])
        self.assertEqual(passages[0]['quote'], passages[1]['quote'])
        for passage in passages:
            actual = citations([dict(evidence_id=passage['evidence_id'])], sources)
            self.assertEqual(actual, [dict(source_id='material-1', quote='🙂代码\n  缩进')])
        for identity in ('forged', passages[0]['evidence_id'].replace('material-1', 'foreign'),
                         evidence_passages([dict(id='material-1', kind='material', text='旧版本')])[0]['evidence_id']):
            with self.assertRaises(DomainError): citations([dict(evidence_id=identity)], sources)
        with self.assertRaises(DomainError):
            citations([dict(source_id='material-1', quote='🙂代码 缩进')], sources)
        with self.assertRaises(DomainError):
            citations([dict(evidence_id=passages[0]['evidence_id'])], sources[1:])
        many = '\n\n'.join(['段'] * 100)
        bounded = evidence_passages([dict(id='large', kind='material', text=many)])
        self.assertEqual(len(bounded), 80)
        self.assertTrue(all(p['quote'] in many for p in bounded))
        self.assertEqual(bounded[-1]['quote'], '\n\n'.join(['段'] * 21))

    def test_evidence_ids_only_visible_to_verify_and_patch_and_compile_canonically(self):
        run = self.confirmed()
        _, read_input = messages_for(run, 'wt_read')
        self.assertNotIn('materials', read_input)
        self.assertNotIn('evidence_passages', read_input)
        reading = simulate(run, 'wt_read')
        for row in reading['results']:
            row.update(status='pass', answer='工具版本为 1.2', excerpt='打开工具。')
        run = self.step(run, reading)
        _, verify_input = messages_for(run, 'wt_verify')
        eid = verify_input['evidence_passages'][0]['evidence_id']
        verified = {'results': [dict(condition_id=r['condition_id'], status='pass', reason='材料支持', citations=[dict(evidence_id=eid)])
                                for r in reading['results']], 'new_issues': []}
        rows = normalize(run, 'wt_verify', verified)['results']
        self.assertTrue(all(row['citations'] == [dict(source_id=run.windtunnel['sources'][0]['id'], quote=run.windtunnel['sources'][0]['text'])] for row in rows))
        run = self.step(run)
        run = self.action(run, 'propose_patch', condition_ids=[conditions(run)['conditions'][0]['id']])
        _, patch_input = messages_for(run, 'wt_patch')
        output = self.grounded_patch(run)
        output['patches'][0]['citations'] = [dict(evidence_id=patch_input['evidence_passages'][0]['evidence_id'])]
        self.assertIn('source_id', normalize(run, 'wt_patch', output)['patches'][0]['citations'][0])

    def test_reading_ids_compile_only_current_title_body_exactly(self):
        run = self.confirmed(title='🙂标题', text='正文\n  缩进\n\n正文\n  缩进')
        _, inputs = messages_for(run, 'wt_read')
        self.assertNotIn('materials', inputs)
        self.assertNotIn('evidence_passages', inputs)
        self.assertNotIn('reading', inputs)
        passages = inputs['reading_passages']
        self.assertNotEqual(passages[1]['excerpt_id'], passages[2]['excerpt_id'])
        reading = simulate(run, 'wt_read')
        for row in reading['results']:
            row.pop('excerpt')
            row.update(status='pass', answer='原稿答案', excerpt_id=passages[1]['excerpt_id'])
        for target in passages:
            output = copy.deepcopy(reading)
            output['results'][0]['excerpt_id'] = target['excerpt_id']
            actual = normalize(run, 'wt_read', output)['results'][0]
            self.assertEqual(actual['excerpt'], target['excerpt'])
            self.assertNotIn('excerpt_id', actual)
        invalid_ids = ['forged', reading_passages(dict(title='旧标题', text=draft(run)['text']))[0]['excerpt_id'],
                       evidence_passages(run.windtunnel['sources'])[0]['evidence_id']]
        for identity in invalid_ids:
            output = copy.deepcopy(reading)
            output['results'][0]['excerpt_id'] = identity
            with self.assertRaises(DomainError): normalize(run, 'wt_read', output)
        output = copy.deepcopy(reading)
        output['results'][0]['excerpt_id'] = ''
        with self.assertRaises(DomainError): normalize(run, 'wt_read', output)
        output['results'][0]['status'] = 'unclear'
        self.assertEqual(normalize(run, 'wt_read', output)['results'][0]['excerpt'], '')
        legacy = simulate(run, 'wt_read')
        legacy['results'][0].update(status='pass', answer='答案', excerpt='正文 缩进')
        with self.assertRaises(DomainError): normalize(run, 'wt_read', legacy)

    def test_reading_passage_tail_covers_long_current_draft(self):
        text = '\n\n'.join(['🙂段落'] * 100)
        passages = reading_passages(dict(title='标题', text=text))
        self.assertEqual(len(passages), 81)
        self.assertEqual(passages[-1]['excerpt'], '\n\n'.join(['🙂段落'] * 21))
        long_text = '正文' * 4000
        run = self.confirmed(text=long_text)
        output = simulate(run, 'wt_read')
        for row in output['results']:
            row.pop('excerpt')
            row.update(status='pass', answer='正文答案', excerpt_id=reading_passages(draft(run))[1]['excerpt_id'])
        self.assertEqual(normalize(run, 'wt_read', output)['results'][0]['excerpt'], long_text)

    def test_boundary_insertions_and_adjacent_replacements_are_order_independent(self):
        for boundary in ('start', 'end'):
            for reverse in (False, True):
                for selection in ('both', 'replacement', 'insert'):
                    with self.subTest(boundary=boundary, reverse=reverse, selection=selection):
                        run = self.report()
                        before = copy.deepcopy(draft(run))
                        run = self.action(run, 'propose_patch', condition_ids=[conditions(run)['conditions'][0]['id']])
                        base = self.grounded_patch(run)['patches'][0]
                        replacement = {**base, 'start': 0, 'end': len(before['text']), 'original': before['text'], 'replacement': '完整修复。'}
                        offset = 0 if boundary == 'start' else len(before['text'])
                        insertion = {**base, 'start': offset, 'end': offset, 'original': '', 'replacement': '补充说明。'}
                        items = [replacement, insertion]
                        if reverse: items.reverse()
                        run = self.step(run, {'patches': items})
                        proposal = run.windtunnel['patches'][-1]
                        chosen = [p for p in proposal['items'] if selection == 'both' or (p['start'] != p['end']) == (selection == 'replacement')]
                        run = self.action(run, 'apply_patch', patch_id=proposal['id'], item_ids=[p['id'] for p in chosen], base_hash=before['hash'])
                        center = '完整修复。' if selection != 'insert' else before['text']
                        expected = center if selection == 'replacement' else ('补充说明。' + center if boundary == 'start' else center + '补充说明。')
                        self.assertEqual(draft(run)['text'], expected)
                        run = self.action(run, 'cancel')
        run = self.report()
        run = self.action(run, 'propose_patch', condition_ids=[conditions(run)['conditions'][0]['id']])
        base = self.grounded_patch(run)['patches'][0]
        text = draft(run)['text']
        adjacent = [{**base, 'start': 0, 'end': 5, 'original': text[:5], 'replacement': '第一段。'},
                    {**base, 'start': 5, 'end': len(text), 'original': text[5:], 'replacement': '第二段。'}]
        self.assertEqual(len(normalize(run, 'wt_patch', {'patches': adjacent})['patches']), 2)
        full = {**base, 'start': 0, 'end': len(text), 'original': text, 'replacement': '修复。'}
        for conflicting in ([full, {**base, 'start': 1, 'end': 1, 'original': ''}], [base, base],
                            [full, {**base, 'start': 1, 'end': len(text), 'original': text[1:]}]):
            with self.assertRaises(DomainError): normalize(run, 'wt_patch', {'patches': conflicting})

    def test_material_update_versions_evidence_and_requires_recheck(self):
        run = self.report()
        prior = copy.deepcopy(current_report(run))
        old_hash = material_hash(run)
        run = self.action(run, 'update_materials', base_material_hash=old_hash, materials=[dict(text='工具版本为 2.0。', title='更新说明')])
        self.assertNotEqual(material_hash(run), old_hash)
        self.assertEqual(run.windtunnel['reports'][0], prior)
        self.assertEqual(run.windtunnel['source_history'][0]['hash'], old_hash)
        with self.assertRaises(DomainError):
            current_report(run)
        with self.assertRaises(DomainError):
            self.action(run, 'update_materials', base_material_hash=old_hash, materials=[])

    def test_checklist_save_replay_reuse_and_cross_account_denial(self):
        run = self.report(feedback=[dict(text='导出文件在哪里？', origin='授权试读记录', provenance='pilot_feedback', permission=True)])
        cs = conditions(run)
        request = dict(run_id=run.run_id, condition_set_id=cs['id'], title='导出教程', key='save-once', version=run.status_version)
        saved = self.wind.save_checklist(self.owner, request)
        self.assertEqual(saved, self.wind.save_checklist(self.owner, request))
        self.assertEqual(len(self.wind.checklists(self.owner, self.account)), 1)
        with self.assertRaises(DomainError):
            self.wind.save_checklist(self.owner, {**request, 'version': run.status_version - 1, 'key': 'stale-version'})
        self.action(run, 'finish')
        other_account = self.account_for(self.owner, '另一个账号')
        with self.assertRaises(DomainError):
            self.wind.create(self.owner, dict(account_id=other_account, title='测试', text='工具说明', checklist={'id': saved['id'], 'version': saved['version']}))
        reused = self.create(checklist={'id': saved['id'], 'version': saved['version']})
        self.assertFalse(conditions(reused)['confirmed'])
        self.assertEqual(conditions(reused)['hash'], cs['hash'])
        self.assertEqual(conditions(reused)['provenance']['version'], saved['version'])
        self.assertTrue(any(s['text'] == '导出文件在哪里？' for s in reused.windtunnel['sources']))

    def test_new_errors_are_separate_and_must_quote_current_draft(self):
        run = self.report()
        d = draft(run)
        run = self.action(run, 'edit_draft', title=d['title'], text=d['text'] + '永久不会失败。', base_hash=d['hash'])
        run = self.action(run, 'recheck', condition_set_id=conditions(run)['id'])
        _, reading_input = messages_for(run, 'wt_read')
        self.assertNotIn('previous_draft', reading_input)
        run = self.step(run)
        _, verify_input = messages_for(run, 'wt_verify')
        self.assertEqual(verify_input['previous_draft']['text'], d['text'])
        result = simulate(run, 'wt_verify')
        result['new_issues'] = [dict(excerpt='永久不会失败', status='insufficient', reason='没有材料支持永久保证', citations=[])]
        normalized = normalize(run, 'wt_verify', result)
        self.assertEqual(len(normalized['results']), len(conditions(run)['conditions']))
        self.assertEqual(len(normalized['new_issues']), 1)
        result['new_issues'][0]['excerpt'] = '稿件不存在的句子'
        with self.assertRaises(DomainError):
            normalize(run, 'wt_verify', result)

    def test_view_hides_owner_and_export_labels_simulation(self):
        run = self.report()
        view = self.wind.view(run)
        self.assertNotIn('owner_id', view)
        self.assertEqual(view['windtunnel']['material_hash'], material_hash(run))
        self.assertIn('模拟流程；不代表模型或真实读者评测', self.wind.export(run))


if __name__ == '__main__':
    unittest.main()
