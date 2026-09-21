import copy
import json
import unittest
from uuid import uuid4

from backend.accounts import PROFILE_FIELDS
from backend.contracts import DomainError
from backend.operations import Operations, now
from backend.store import Store
import test_operations
import test_demo_web


class AccountTests(unittest.TestCase):
    setUp = test_operations.OperationsTests.setUp
    tearDown = test_operations.OperationsTests.tearDown
    command = test_operations.OperationsTests.command
    confirmed = test_operations.OperationsTests.confirmed
    publication = test_operations.OperationsTests.publication

    def profile(self, identity='', name='穿搭日记'):
        return dict(id=identity, name=name, platform='xiaohongshu',
                    profile={**{k: '' for k in PROFILE_FIELDS}, 'weekly_frequency': 3})

    def test_stable_identity_rename_and_import_independent_of_model(self):
        state = self.command('save_account', self.profile())
        account = state['accounts'][-1]
        post = dict(account_id=account['id'], title='旧衣新搭', body='我的真实记录',
                    url='https://www.xiaohongshu.com/explore/old', published_at=now(),
                    format='image_text', pillar='衣橱', traffic='organic')
        state = self.command('import_post', post)
        imported = state['publications'][0]
        self.assertEqual(imported['mode'], 'imported')
        self.assertIsNone(imported['review_ref'])
        self.command('save_account', self.profile(account['id'], '改名后的日记'))
        state = Operations(Store(self.store.path)).read(self.owner)
        self.assertEqual(state['publications'][0]['account_id'], account['id'])
        context = self.ops.context(self.owner, {'account_id': account['id']}, 'live')
        self.assertEqual(context['account'], '改名后的日记')
        self.assertEqual(context['history'][0]['id'], imported['id'])
        with self.assertRaises(DomainError): self.command('import_post', post)
        with self.assertRaises(DomainError): self.ops.context('other', {'account_id': account['id']}, 'live')
        with self.assertRaises(DomainError): self.command('save_account', {**self.profile(account['id']), 'platform':'douyin'})

    def test_legacy_migration_is_stable_and_non_destructive(self):
        run, pub = self.publication()
        state = self.ops.read(self.owner)
        for key in ('accounts','preferences','analyses','plans','competitors','experiments','operations_schema_version'): state.pop(key)
        state['publications'][0].pop('account_id')
        with self.store.connect() as db:
            db.execute('UPDATE operations SET payload=? WHERE owner=?', (json.dumps(state), self.owner))
        first = self.ops.read(self.owner)
        self.assertEqual(first, Operations(Store(self.store.path)).read(self.owner))
        self.assertEqual(first['publications'][0]['content'], pub['content'])
        self.assertEqual(first['publications'][0]['account_id'], first['accounts'][0]['id'])

    def test_edit_history_is_atomic_idempotent_and_not_performance_evidence(self):
        account = self.command('save_account', self.profile())['accounts'][-1]
        from backend.demo import validate_brief
        context = validate_brief(dict(topic='穿搭', audience='学生', tone='真实'))
        context.update(mode='simulation', operations=self.ops.context(self.owner, {'account_id':account['id']}, 'simulation'))
        run = self.store.create(self.owner, 'snapshot', context)
        for _ in range(10):
            if run.run_status == 'WAITING_USER': break
            run = self.store.command(run.run_id, self.owner, run.status_version, str(uuid4()), 'demo_step')
        before = copy.deepcopy(run)
        content = {**run.drafts[-1]['content'], 'selected_title':'我更喜欢的开头'}
        run = self.store.command(run.run_id, self.owner, run.status_version, 'edit-once', 'edit', {'content':content})
        self.store.command(before.run_id, self.owner, before.status_version, 'edit-once', 'edit', {'content':content})
        changes = self.ops.read(self.owner)['preferences']
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]['account_id'], account['id'])
        self.assertIn('不代表传播效果', changes[0]['interpretation'])
        self.assertIsNone(run.review)
        self.assertEqual(run.drafts[0], before.drafts[0])


class RecoveryTests(unittest.TestCase):
    setUp = test_demo_web.DemoWebTests.setUp
    tearDown = test_demo_web.DemoWebTests.tearDown
    request = test_demo_web.DemoWebTests.request
    create = test_demo_web.DemoWebTests.create

    def test_restore_owner_in_fresh_browser_and_rotate_recovery_key(self):
        run = self.create()
        status, result = self.request('POST', '/api/session/recovery', {})
        self.assertEqual(status, 200)
        code = result['recovery_code']
        self.cookie=''; self.csrf=''
        self.request('GET','/api/session')
        self.assertEqual(self.request('GET', '/api/runs')[1], [])
        self.assertEqual(self.request('POST','/api/session/restore', {'recovery_code':'bad'})[0], 403)
        status, result = self.request('POST','/api/session/restore', {'recovery_code':code})
        self.assertEqual(status, 200); self.csrf=result['csrf']
        self.assertEqual(self.request('GET','/api/runs')[1][0]['run_id'],run['run_id'])
        self.request('POST','/api/session/recovery', {})
        self.assertEqual(self.request('POST','/api/session/restore', {'recovery_code':code})[0], 403)
        with self.store.connect() as db:
            self.assertNotIn(code, str(db.execute('SELECT * FROM recovery_keys').fetchall()))

class CreatorContextTests(unittest.TestCase):
    def test_context_artifacts_do_not_turn_preferences_into_statistics(self):
        from backend.creator_context import enrich
        context = dict(topic='旧衣搭配',audience='学生',operations=dict(account_id='a',
            profile={'revision':2,'profile':{'positioning':'日常衣橱','goal':'增加收藏','banned':'保证有效'}},
            history=[{'id':'post'}], metrics=[{'publication_id':'post','values':{'views':100}}],
            preferences=[{'changes':{'body':{'before':'x','after':'y'}}}], memories=[]))
        audience = enrich('audience',{},context)
        self.assertEqual(audience['sample_size'],1)
        self.assertEqual(audience['confidence'],'low')
        research = enrich('research',{'prohibited_claims':['无依据效果']},context)
        self.assertIn('暂无可核验',research['topic_card']['why_now'])
        strategy = enrich('strategy',dict(angle='衣橱清单',reader='学生'),context)
        self.assertEqual(strategy['content_brief']['goal'],'增加收藏')
        self.assertEqual(strategy['content_brief']['profile_revision'],2)
        self.assertIn('暂无经过验证',strategy['content_brief']['publishing_window'])
        context['operations']['metrics']=[]
        self.assertEqual(enrich('audience',{},context)['sample_size'],0)

    def test_account_banned_expression_is_checked_in_simulation(self):
        from backend.demo import review
        from backend.workflow import Run, digest
        run=Run('owner','snapshot',context={'operations':{'profile':{'profile':{'banned':'夸张词、保证变美'}}}})
        content={'selected_title':'保证变美','body':'这是一份搭配建议','cta':'','tags':[]}
        run.drafts=[{'ref':'draft@1','content':content,'content_hash':digest(content)}]
        report=review(run)
        self.assertEqual(report['decision'],'revision_required')
        self.assertTrue(any(i['excerpt']=='保证变美' for i in report['issues']))
