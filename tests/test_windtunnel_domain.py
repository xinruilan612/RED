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
                                material_hash, messages_for, normalize, simulate, stage_sources)
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
        return self.wind.create(self.owner, dict(account_id=self.account, title='工具入门', text='打开工具。点击导出。',
                                                scene='没有经验的学生读者', materials=[{'text': '工具版本为 1.2，导出后保存至下载目录。', 'title': '工具官方说明'}], **overrides))

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

    def test_reading_whitelist_excludes_material_feedback_old_answers_and_profile(self):
        run = self.confirmed(feedback=[dict(text='秘密答案：1.2版本', origin='2026-09 试读', provenance='pilot_feedback', permission=True)])
        run.context['operations'] = {'profile': {'secret': 'PROFILE_SECRET'}}
        run.windtunnel['reports'] = [{'results': ['REPORT_SECRET']}]
        run.windtunnel['reading'] = [{'answer': 'OLD_READING_SECRET'}]
        _, inputs = messages_for(run, 'wt_read')
        serialized = json.dumps(inputs, ensure_ascii=False)
        self.assertEqual(set(inputs), {'scene', 'draft', 'conditions'})
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
        run = self.step(run)
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
        output = simulate(run, 'wt_patch')
        output['patches'].append(copy.deepcopy(output['patches'][0]))
        with self.assertRaises(DomainError):
            normalize(run, 'wt_patch', output)
        output = simulate(run, 'wt_patch')
        output['patches'][0]['replacement'] = '保证导出成功，永久免费。'
        with self.assertRaises(DomainError):
            normalize(run, 'wt_patch', output)
        output['patches'][0]['replacement'] = '本品免烫且永久免费。待核实'
        with self.assertRaises(DomainError):
            normalize(run, 'wt_patch', output)

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
