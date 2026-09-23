"""Isolated SQLite/PG experiment loop. Past dates are controlled test fixtures."""
import json
import os
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from backend.contracts import DomainError
from backend.demo import validate_brief
from backend.experiments import recommend
from backend.live import messages_for
from backend.operations import Operations
from backend.provider import Config
from backend.service import Service
from backend.store import Store
from backend.worker import Worker


class ExperimentResultTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / 'experiment.sqlite')
        self.prepare()

    def prepare(self):
        self.owner = 'experiment-owner'
        self.service = Service(self.store, Config())
        self.ops = self.service.operations
        self.published = datetime.now(timezone.utc) - timedelta(hours=26)
        self.clock = patch('backend.operations.now', return_value=(self.published - timedelta(hours=1)).isoformat())
        self.clock.start()
        state = self.command('load_sample', {})
        self.account = next(a for a in state['accounts'] if a.get('demo_sample'))
        self.profile(pillars='搭配清单')

    def tearDown(self):
        self.clock.stop()
        self.tmp.cleanup()

    def command(self, action, payload, owner=None):
        owner = owner or self.owner
        return self.ops.command(owner, dict(action=action, payload=payload,
            version=self.ops.read(owner)['version'], key=str(uuid4())))

    def profile(self, **changes):
        profile = self.account['profile'] | changes
        state = self.command('save_account', dict(id=self.account['id'], name=self.account['name'],
                                                  platform=self.account['platform'], profile=profile))
        self.account = next(a for a in state['accounts'] if a['id'] == self.account['id'])

    def decision(self, **extra):
        payload = dict(account_id=self.account['id'], source_type='simulation', window='24h', format='image_text') | extra
        decision = self.command('recommend_experiment', payload)['experiments'][0]
        self.command('experiment_status', {'id': decision['id'], 'status': 'accepted'})
        return next(e for e in self.ops.read(self.owner)['experiments'] if e['id'] == decision['id'])

    def confirmed(self, decision, background=False, forged=None, workflow='professional'):
        mode = 'simulation' if decision['source_type'] == 'simulation' else 'live'
        context = dict(account_id=self.account['id'], platform=self.account['platform'], format=decision['format'],
                       experiment_id=decision['id'])
        brief = dict(topic='衣橱搭配实验', audience='学生', tone='真实', material='我有两件白衬衫。',
                     mode=mode, workflow=workflow, operations=context)
        if forged or mode == 'live':
            # A deterministic live-labelled domain fixture, never a paid model call.
            raw = validate_brief({k: v for k, v in brief.items() if k not in ('mode', 'operations', 'workflow')})
            raw.update(mode=mode, workflow=workflow, operations=self.ops.context(self.owner, context, mode))
            if forged:
                forged(raw)
            run = self.store.create(self.owner, str(uuid4()), raw)
        else:
            result = self.service.create(self.owner, brief)
            run = self.store.get(result['run_id'], self.owner)
        if background:
            self.service.background(self.owner, run.run_id, dict(action='start', version=run.status_version, key=str(uuid4())))
            Worker(self.service).once()
            run = self.store.get(run.run_id, self.owner)
        else:
            for _ in range(12):
                if run.run_status == 'WAITING_USER':
                    break
                run = self.store.command(run.run_id, self.owner, run.status_version, str(uuid4()), 'demo_step')
        self.assertEqual(run.wait_reason, 'final_confirmation')
        return self.store.command(run.run_id, self.owner, run.status_version, str(uuid4()), 'accept',
                                  dict(draft_ref=run.drafts[-1]['ref'], review_ref=run.review['ref']))

    def publication(self, decision, background=False):
        run = self.confirmed(decision, background)
        return self.command('prepare', dict(run_id=run.run_id, draft_ref=run.accepted_ref))['publications'][0]

    def publish(self, pub):
        self.command('approve', {'id': pub['id']})
        with patch('backend.operations.now', return_value=self.published.isoformat()):
            self.command('simulate', {'id': pub['id']})

    def metadata(self, pub, decision, **extra):
        return self.command('post_metadata', dict(id=pub['id'], format=decision['format'],
                    pillar=decision['chosen_pillar'], traffic='organic') | extra)

    def metric(self, pub, **extra):
        return self.command('metrics', dict(id=pub['id'], window='24h', views=1000, likes=40, saves=20,
            comments=10, shares=5, observed_at=(self.published + timedelta(hours=24)).isoformat()) | extra)

    def result(self, decision):
        state = self.command('evaluate_experiment', {'id': decision['id']})
        return next(r for r in state['experiment_results'] if r['experiment_id'] == decision['id'])

    def mutate_state(self, fn):
        """Corrupt only isolated fixtures to prove service-side revalidation."""
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            state = self.ops.read(self.owner, db)
            fn(state)
            db.execute('UPDATE operations SET payload=? WHERE owner=?', (json.dumps(state), self.owner))

    def create_brief(self, decision):
        return dict(topic='事务边界实验', audience='测试读者', tone='清楚', material='虚构测试材料',
                    mode='simulation', workflow='quick', operations=dict(account_id=self.account['id'],
                    platform=self.account['platform'], format=decision['format'], experiment_id=decision['id']))

    def assert_creation_counts(self, runs=0):
        with self.store.connect() as db:
            for table, expected in (('runs', runs), ('runtime_jobs', 0), ('live_calls', 0), ('reservations', 0)):
                self.assertEqual(db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0], expected, table)

    def test_creation_rechecks_revocation_committed_after_initial_context(self):
        decision = self.decision(); initial_context = self.ops.context

        def revoke_after_validation(owner, data, mode):
            context = initial_context(owner, data, mode)
            self.command('experiment_status', dict(id=decision['id'], status='revoked'))
            return context

        with patch.object(self.ops, 'context', side_effect=revoke_after_validation), self.assertRaises(DomainError):
            self.service.create(self.owner, self.create_brief(decision))
        self.assert_creation_counts()

    def test_creation_rechecks_evidence_correction_committed_after_initial_context(self):
        decision = self.decision(); initial_context = self.ops.context
        metric = next(m for m in self.ops.read(self.owner)['metrics'] if m['id'] in decision['metric_refs'])

        def correct_after_validation(owner, data, mode):
            context = initial_context(owner, data, mode)
            self.command('metrics', dict(id=metric['publication_id'], window=metric['window'],
                observed_at=metric['observed_at'], **(metric['values'] | {'likes': metric['values']['likes'] + 1})))
            return context

        with patch.object(self.ops, 'context', side_effect=correct_after_validation), self.assertRaises(DomainError):
            self.service.create(self.owner, self.create_brief(decision))
        self.assert_creation_counts()

    def test_creation_rechecks_publication_binding_committed_after_initial_context(self):
        decision = self.decision(); run = self.confirmed(decision); initial_context = self.ops.context

        def bind_after_validation(owner, data, mode):
            context = initial_context(owner, data, mode)
            self.command('prepare', dict(run_id=run.run_id, draft_ref=run.accepted_ref))
            return context

        with patch.object(self.ops, 'context', side_effect=bind_after_validation), self.assertRaises(DomainError):
            self.service.create(self.owner, self.create_brief(decision))
        self.assert_creation_counts(runs=1)  # Only the earlier, already-confirmed task exists.

    def test_creation_rechecks_frozen_snapshot_and_scope_before_insert(self):
        decision = self.decision(); initial_context = self.ops.context
        for target, field, value in (('experiment', 'hypothesis', '伪造内容'),
                ('experiment', 'decision_hash', 'forged'), ('operations', 'account_id', 'another-account'),
                ('operations', 'platform', 'douyin'), ('operations', 'format', 'video')):
            def forge_after_validation(owner, data, mode):
                context = initial_context(owner, data, mode)
                (context['experiment'] if target == 'experiment' else context)[field] = value
                return context
            with self.subTest(field=field), patch.object(self.ops, 'context', side_effect=forge_after_validation):
                with self.assertRaises(DomainError):
                    self.service.create(self.owner, self.create_brief(decision))
                self.assert_creation_counts()

    def test_creation_guard_uses_existing_write_connection_after_retrieval(self):
        decision = self.decision(); events = []
        guard = self.ops.validate_creation

        def retrieve(*args):
            self.assertEqual(events, [])
            events.append('retrieval')
            return dict(sources=[])

        def validate_in_transaction(db, run):
            self.assertEqual(events, ['retrieval'])
            # The validator must reuse Store.create's connection, not open another
            # one while the write lock is held (which can deadlock PostgreSQL).
            with patch.object(self.store, 'connect', side_effect=AssertionError('unexpected nested connection')):
                guard(db, run)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM runs').fetchone()[0], 0)
            events.append('guard')

        with patch.object(self.service.knowledge, 'retrieve', side_effect=retrieve), \
                patch.object(self.ops, 'validate_creation', side_effect=validate_in_transaction):
            response = self.service.create(self.owner, self.create_brief(decision) | {'knowledge': {'enabled': True}})
        self.assertEqual(events, ['retrieval', 'guard'])
        self.assertEqual(response['context']['operations']['experiment']['decision_hash'], decision['decision_hash'])
        self.assert_creation_counts(runs=1)

    def test_creation_guard_preserves_ordinary_and_promotion_service_paths(self):
        brief = dict(topic='普通素材整理', audience='学生', tone='清楚', material='原创测试材料', mode='simulation')
        ordinary = self.service.create('ordinary-owner', brief)
        self.assertEqual(ordinary['run_status'], 'QUEUED')
        self.assertNotIn('operations', ordinary['context'])
        service = self.command('save_service', dict(id='', account_id=self.account['id'], name='虚构摄影服务',
            offering='拍摄', target_customer='学生', delivery='线下', price='', availability='', contact='',
            public_fields=['offering', 'target_customer', 'delivery'], active=True))['services'][-1]
        promotion = self.command('create_promotion_brief', dict(account_id=self.account['id'],
            service_id=service['id'], goal='trust', customer_problem='如何准备拍摄',
            problem_source='user_provided', portfolio_ids=[]))['promotion_briefs'][0]
        result = self.service.create(self.owner, brief | {'operations': dict(account_id=self.account['id'],
            platform=self.account['platform'], promotion_brief_id=promotion['id'])})
        self.assertEqual(result['context']['operations']['promotion']['id'], promotion['id'])
        self.assertIn('服务：拍摄', result['context']['material'])
        self.assertEqual(result['context']['operations']['promotion']['public_service']['name'], '虚构摄影服务')
        self.assert_creation_counts(runs=2)

    def test_background_exact_approval_to_persisted_observation_and_idempotent_recompute(self):
        decision = self.decision()
        self.assertEqual(self.result(decision)['status'], 'pending_publication')
        pub = self.publication(decision, background=True)
        self.assertEqual(pub['experiment_id'], decision['id'])
        self.assertEqual(pub['experiment_snapshot']['decision_hash'], decision['decision_hash'])
        self.assertEqual((pub['pillar'], pub['traffic'], pub['metadata_confirmed']), ('未分类', 'unknown', False))
        self.publish(pub)
        self.assertEqual(self.result(decision)['status'], 'conditions_mismatch')
        self.metadata(pub, decision)
        self.assertEqual(self.result(decision)['status'], 'pending_metrics')
        self.metric(pub)
        result = self.result(decision)
        self.assertEqual(result['status'], 'observed')
        self.assertEqual(result['observed_reward'], 135.0)
        self.assertEqual(result['baseline_reward'], decision['baseline_reward'])
        self.assertEqual(result['baseline_metric_refs'], decision['baseline_metric_refs'])
        self.assertEqual(self.result(decision)['id'], result['id'])
        self.assertEqual(Operations(Store(self.store.path)).read(self.owner)['experiment_results'], self.ops.read(self.owner)['experiment_results'])
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM live_calls').fetchone()[0], 0)

    def test_no_baseline_is_observed_without_invented_zero_or_difference(self):
        self.profile(pillars='搭配清单, 新栏目')
        decision = self.decision()
        pub = self.publication(decision)
        self.publish(pub); self.metadata(pub, decision); self.metric(pub)
        result = self.result(decision)
        self.assertEqual(result['status'], 'observed_no_baseline')
        self.assertIsNone(result['baseline_reward']); self.assertIsNone(result['difference'])
        self.assertEqual(result['baseline_metric_refs'], [])

    def test_window_incomplete_and_explicit_actual_conditions_are_not_guessed(self):
        decision = self.decision()
        pub = self.publication(decision)
        self.publish(pub); self.metadata(pub, decision)
        self.metric(pub, window='72h')
        self.assertEqual(self.result(decision)['status'], 'pending_metrics')
        self.metric(pub, observed_at=(self.published + timedelta(hours=1)).isoformat())
        self.assertEqual(self.result(decision)['status'], 'window_mismatch')
        self.metric(pub, saves=None)
        self.assertEqual(self.result(decision)['status'], 'incomplete')
        self.metric(pub, saves=0)
        self.assertEqual(self.result(decision)['status'], 'observed')
        self.metadata(pub, decision, traffic='paid')
        self.assertEqual(self.result(decision)['status'], 'conditions_mismatch')
        with self.assertRaises(DomainError):
            self.metric(pub, observed_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())

    def test_newly_published_real_time_is_not_a_completed_24h_observation(self):
        decision = self.decision()
        pub = self.publication(decision)
        self.published = datetime.now(timezone.utc)
        self.publish(pub); self.metadata(pub, decision)
        self.metric(pub, observed_at=datetime.now(timezone.utc).isoformat())
        self.assertEqual(self.result(decision)['status'], 'window_mismatch')

    def test_recommendation_filters_platform_format_metric_source_and_window(self):
        state = self.ops.read(self.owner)
        sample = state['metrics'][0]
        post = next(p for p in state['publications'] if p['id'] == sample['publication_id'])
        for target, field, value, reason in ((post, 'format', 'video', '内容形式'),
                (post, 'platform', 'douyin', '平台'), (post, 'provenance', 'manual', '来源'),
                (sample, 'source_type', 'manual', '来源'), (sample, 'window', '72h', '窗口')):
            original = target[field]; target[field] = value
            result = recommend(state, self.account['id'], 'simulation', '24h', self.published.isoformat(), 'image_text')
            self.assertNotIn(sample['id'], result['metric_refs'])
            excluded = next(r for r in result['excluded'] if r['metric_id'] == sample['id'])
            self.assertTrue(any(reason in r for r in excluded['reasons']))
            self.assertIn(sample['id'], result['dependency_metric_refs'])
            target[field] = original

    def test_unaccepted_wrong_owner_account_platform_source_and_format_are_rejected(self):
        decision = self.decision()
        base = dict(account_id=self.account['id'], platform='xiaohongshu', format='image_text', experiment_id=decision['id'])
        for owner, mode, change in ((self.owner, 'live', {}), (self.owner, 'simulation', {'format': 'video'}),
                (self.owner, 'simulation', {'platform': 'douyin'}), ('stranger', 'simulation', {}),
                (self.owner, 'simulation', {'account_id': self.ops.read(self.owner)['accounts'][0]['id']})):
            with self.subTest(owner=owner, mode=mode, change=change), self.assertRaises(DomainError):
                self.ops.context(owner, base | change, mode)
        with self.assertRaises(DomainError):
            self.command('recommend_experiment', dict(account_id=self.account['id'], source_type='simulation', window='24h', platform='douyin'))
        self.command('experiment_status', {'id': decision['id'], 'status': 'revoked'})
        with self.assertRaises(DomainError):
            self.ops.context(self.owner, base, 'simulation')
        with self.assertRaises(DomainError):
            self.command('evaluate_experiment', {'id': decision['id']}, owner='stranger')

    def test_revocation_after_creation_blocks_prepare_and_after_prepare_blocks_publish(self):
        first = self.decision(); run = self.confirmed(first)
        self.command('experiment_status', {'id': first['id'], 'status': 'revoked'})
        with self.assertRaises(DomainError):
            self.command('prepare', dict(run_id=run.run_id, draft_ref=run.accepted_ref))
        second = self.decision(); pub = self.publication(second)
        self.command('approve', {'id': pub['id']})
        self.command('experiment_status', {'id': second['id'], 'status': 'revoked'})
        with self.assertRaises(DomainError):
            self.command('simulate', {'id': pub['id']})

    def test_forged_snapshot_and_wrong_exact_version_cannot_bind(self):
        decision = self.decision()
        run = self.confirmed(decision, forged=lambda c: c['operations']['experiment'].update(chosen_pillar='伪造栏目'))
        with self.assertRaises(DomainError):
            self.command('prepare', dict(run_id=run.run_id, draft_ref=run.accepted_ref))
        run = self.confirmed(decision)
        with self.assertRaises(DomainError):
            self.command('prepare', dict(run_id=run.run_id, draft_ref='wrong'))
        with self.store.connect() as db:
            run.drafts[-1]['content']['body'] = '确认后被篡改的正文'
            db.execute('UPDATE runs SET payload=? WHERE id=?', (json.dumps(asdict(run)), run.run_id))
        with self.assertRaises(DomainError):
            self.command('prepare', dict(run_id=run.run_id, draft_ref=run.accepted_ref))

    def test_duplicate_binding_and_missing_frozen_publication_snapshot_are_rejected(self):
        decision = self.decision(); first = self.confirmed(decision); second = self.confirmed(decision)
        pub = self.command('prepare', dict(run_id=first.run_id, draft_ref=first.accepted_ref))['publications'][0]
        with self.assertRaises(DomainError):
            self.command('prepare', dict(run_id=second.run_id, draft_ref=second.accepted_ref))
        with self.assertRaises(DomainError):
            self.confirmed(decision)
        self.mutate_state(lambda s: s['publications'][0].pop('experiment_snapshot'))
        with self.assertRaises(DomainError):
            self.command('approve', {'id': pub['id']})

    def test_metric_correction_keeps_old_result_then_recomputes_without_revoking_experiment(self):
        decision = self.decision(); pub = self.publication(decision)
        self.publish(pub); self.metadata(pub, decision); self.metric(pub)
        old = self.result(decision)
        state = self.metric(pub, saves=30)
        retained = next(r for r in state['experiment_results'] if r['id'] == old['id'])
        self.assertEqual(retained['status'], 'superseded')
        self.assertEqual(retained['metric_snapshot']['values']['saves'], 20)
        self.assertEqual(next(e for e in state['experiments'] if e['id'] == decision['id'])['status'], 'accepted')
        new = self.result(decision)
        self.assertNotEqual(new['id'], old['id']); self.assertEqual(new['metric_revision'], 2)
        self.assertEqual(new['observed_reward'], 165.0)
        self.assertEqual(new['baseline_reward'], old['baseline_reward'])

    def test_excluded_correction_invalidates_recommendation_and_old_result(self):
        sample = self.ops.read(self.owner)['metrics'][0]
        self.command('metrics', dict(id=sample['publication_id'], window='24h', observed_at=sample['observed_at'],
                                     **(sample['values'] | {'views': None})))
        decision = self.decision(); pub = self.publication(decision)
        self.publish(pub); self.metadata(pub, decision); self.metric(pub)
        old = self.result(decision)
        state = self.command('metrics', dict(id=sample['publication_id'], window='24h',
                              observed_at=sample['observed_at'], **sample['values']))
        self.assertEqual(state['experiments'][0]['status'], 'superseded')
        self.assertEqual(next(r for r in state['experiment_results'] if r['id'] == old['id'])['status'], 'superseded')
        self.assertEqual(self.result(decision)['status'], 'blocked')

    def test_scored_metadata_correction_and_revocation_invalidate_but_do_not_delete(self):
        decision = self.decision(); pub = self.publication(decision)
        self.publish(pub); self.metadata(pub, decision); self.metric(pub)
        old = self.result(decision)
        baseline_pub = decision['evidence'][0]['publication_id']
        self.command('post_metadata', dict(id=baseline_pub, format='video', pillar='搭配清单', traffic='organic'))
        self.assertEqual(self.result(decision)['status'], 'blocked')
        self.assertIn(old['id'], [r['id'] for r in self.ops.read(self.owner)['experiment_results']])
        second = self.decision(); self.result(second)
        self.command('experiment_status', {'id': second['id'], 'status': 'revoked'})
        self.assertEqual(self.result(second)['status'], 'blocked')

    def test_new_future_samples_never_rewrite_frozen_baseline_or_invalidate_original(self):
        decision = self.decision(); baseline = decision['baseline_reward']
        second = self.decision(); pub = self.publication(second)
        self.publish(pub); self.metadata(pub, second); self.metric(pub, saves=900)
        current = next(e for e in self.ops.read(self.owner)['experiments'] if e['id'] == decision['id'])
        self.assertEqual(current['status'], 'accepted')
        self.assertEqual(current['baseline_reward'], baseline)
        self.assertEqual(current['decision_hash'], decision['decision_hash'])

    def test_actual_conditions_correction_supersedes_result_and_can_be_truthfully_recomputed(self):
        decision = self.decision(); pub = self.publication(decision)
        self.publish(pub); self.metadata(pub, decision); self.metric(pub)
        old = self.result(decision)
        self.metadata(pub, decision, format='video')
        self.assertEqual(self.result(decision)['status'], 'conditions_mismatch')
        self.metadata(pub, decision)
        self.assertEqual(self.result(decision)['status'], 'observed')
        retained = next(r for r in self.ops.read(self.owner)['experiment_results'] if r['id'] == old['id'])
        self.assertEqual(retained['status'], 'superseded')
        self.assertEqual(retained['actual']['format'], 'image_text')

    def test_legacy_decisions_are_read_only_and_cannot_authorize_new_publications(self):
        decision = self.decision()
        self.mutate_state(lambda s: s['experiments'][0].pop('schema_version'))
        current = self.ops.read(self.owner)['experiments'][0]
        self.assertEqual(current['status'], 'superseded')
        with self.assertRaises(DomainError):
            self.confirmed(decision)

    def test_requested_video_and_image_text_formats_override_platform_defaults(self):
        video = self.decision(format='video')
        run = self.confirmed(video)
        self.assertIn('非成片', run.drafts[-1]['content']['body'])
        self.assertIn('视频脚本', messages_for(run, 'body')[0][0]['content'])
        image = self.decision(format='image_text')
        run = self.confirmed(image)
        self.assertNotIn('非成片', run.drafts[-1]['content']['body'])
        self.assertNotIn('目标形式是视频脚本', messages_for(run, 'body')[0][0]['content'])

    def test_quick_video_and_image_text_respect_format_and_still_require_exact_approval(self):
        for content_format, video in (('video', True), ('image_text', False)):
            run = self.confirmed(self.decision(format=content_format), workflow='quick')
            self.assertEqual('非成片' in run.drafts[-1]['content']['body'], video)
            self.assertEqual(run.run_status, 'SUCCEEDED')
            self.assertEqual(run.review['draft_ref'], run.accepted_ref)

    def test_manual_record_domain_fixture_preserves_source_and_rejects_backdating(self):
        decision = self.decision(source_type='manual')
        self.assertEqual(decision['sample_size'], 0)  # Simulated history is excluded.
        pub = self.publication(decision)
        self.command('approve', {'id': pub['id']})
        with self.assertRaises(DomainError):
            self.command('simulate', {'id': pub['id']})
        record = dict(id=pub['id'], url='https://www.xiaohongshu.com/explore/domain-fixture',
                      published_at=self.published.isoformat())
        with self.assertRaises(DomainError):
            self.command('record', record | {'published_at': (self.published - timedelta(hours=2)).isoformat()})
        self.command('record', record)
        self.metadata(pub, decision); self.metric(pub)
        result = self.result(decision)
        self.assertEqual(result['status'], 'observed_no_baseline')
        self.assertEqual(result['source_type'], 'manual')
        self.assertEqual(result['metric_snapshot']['source_type'], 'manual')
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM live_calls').fetchone()[0], 0)

    def test_results_reject_client_supplied_metrics_rewards_or_cross_owner_runs(self):
        decision = self.decision(); run = self.confirmed(decision)
        with self.assertRaises(DomainError):
            self.command('evaluate_experiment', {'id': decision['id'], 'observed_reward': 9999})
        with self.assertRaises(DomainError):
            self.command('prepare', {'run_id': run.run_id, 'draft_ref': run.accepted_ref}, owner='stranger')


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'PostgreSQL integration requires TEST_DATABASE_URL')
class PostgresExperimentResultTests(ExperimentResultTests):
    def setUp(self):
        import psycopg
        self.tmp = tempfile.TemporaryDirectory()
        self.schema = 'youji_test_' + uuid4().hex
        self.base = os.environ['TEST_DATABASE_URL']
        with psycopg.connect(self.base, autocommit=True) as db:
            db.execute('CREATE SCHEMA ' + self.schema)
        self.store = Store(self.base + ('&' if '?' in self.base else '?') + 'options=-csearch_path%3D' + self.schema)
        self.prepare()

    def tearDown(self):
        import psycopg
        super().tearDown()
        with psycopg.connect(self.base, autocommit=True) as db:
            db.execute('DROP SCHEMA ' + self.schema + ' CASCADE')
