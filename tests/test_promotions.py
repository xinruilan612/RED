"""Service promotion records reuse the existing owner/account and publication guards."""
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from backend.contracts import DomainError
from backend.demo import validate_brief
from backend.operations import Operations, now
from backend.store import Store


class PromotionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / 'promotion.sqlite')
        self.ops = Operations(self.store)
        self.owner = 'alice'
        self.account = self.ops.read(self.owner)['accounts'][0]

    def tearDown(self):
        self.temp.cleanup()

    def command(self, action, payload, owner=None):
        owner = owner or self.owner
        state = self.ops.read(owner)
        return self.ops.command(owner, {'action': action, 'payload': payload, 'version': state['version'], 'key': str(uuid4())})

    def service(self):
        state = self.command('save_service', {
            'id': '', 'account_id': self.account['id'], 'name': '校园毕业照',
            'offering': '校园毕业照拍摄与基础修图', 'target_customer': '本校毕业生',
            'delivery': '校内线下拍摄', 'price': '299 元起，具体按人数确认',
            'availability': '', 'contact': '站内私信说明人数和日期',
            'public_fields': ['offering', 'target_customer', 'delivery', 'price', 'contact'], 'active': True,
        })
        return state['services'][-1]

    def portfolio(self, service, public=True):
        state = self.command('save_portfolio', {
            'id': '', 'service_id': service['id'], 'title': '图书馆毕业照',
            'description': '用户确认的校园拍摄案例描述', 'role': '独立拍摄和修图',
            'facts': '在图书馆外完成一组双人毕业照', 'link': '',
            'public_confirmed': public, 'active': True,
        })
        return state['portfolio_items'][-1]

    def brief(self, service, portfolio):
        state = self.command('create_promotion_brief', {
            'account_id': self.account['id'], 'service_id': service['id'], 'goal': 'trust',
            'customer_problem': '第一次拍毕业照不会摆姿势怎么办', 'problem_source': 'user_provided',
            'portfolio_ids': [portfolio['id']],
        })
        return state['promotion_briefs'][0]

    def published(self, brief):
        base = validate_brief({'topic': brief['topic'], 'audience': brief['audience'], 'tone': '真实清楚'})
        base.update(mode='simulation', operations=self.ops.context(self.owner, {
            'account_id': self.account['id'], 'promotion_brief_id': brief['id']}, 'simulation'))
        run = self.store.create(self.owner, str(uuid4()), base)
        for _ in range(12):
            if run.run_status == 'WAITING_USER':
                break
            run = self.store.command(run.run_id, self.owner, run.status_version, str(uuid4()), 'demo_step')
        run = self.store.command(run.run_id, self.owner, run.status_version, str(uuid4()), 'accept', {
            'draft_ref': run.drafts[-1]['ref'], 'review_ref': run.review['ref']})
        state = self.command('prepare', {'run_id': run.run_id, 'draft_ref': run.accepted_ref})
        publication = state['publications'][0]
        self.command('approve', {'id': publication['id']})
        return self.command('simulate', {'id': publication['id']})['publications'][0]

    def test_public_permissions_and_versioned_brief(self):
        service = self.service()
        private = self.portfolio(service, public=False)
        with self.assertRaises(DomainError):
            self.command('create_promotion_brief', {
                'account_id': self.account['id'], 'service_id': service['id'], 'goal': 'trust',
                'customer_problem': '如何准备', 'problem_source': 'model_hypothesis',
                'portfolio_ids': [private['id']]})
        public = self.portfolio(service)
        brief = self.brief(service, public)
        context = self.ops.context(self.owner, {'account_id': self.account['id'], 'promotion_brief_id': brief['id']}, 'simulation')
        self.assertEqual(context['promotion']['service_version'], 1)
        self.assertIn('299 元起', context['promotion']['material'])
        self.assertNotIn('可约时间：', context['promotion']['material'])
        self.assertEqual(context['promotion']['problem_source_label'], '用户提供')

        self.command('save_service', {**{k: service[k] for k in ('id', 'account_id', 'name', 'offering', 'target_customer',
            'delivery', 'price', 'availability', 'contact', 'public_fields', 'active')}, 'price': '价格面议'})
        state = self.ops.read(self.owner)
        self.assertEqual(state['promotion_briefs'][0]['status'], 'needs_review')
        with self.assertRaises(DomainError):
            self.ops.context(self.owner, {'account_id': self.account['id'], 'promotion_brief_id': brief['id']}, 'simulation')

    def test_publication_inquiry_summary_and_correction_invalidation(self):
        service = self.service()
        portfolio = self.portfolio(service)
        brief = self.brief(service, portfolio)
        publication = self.published(brief)
        self.assertEqual(publication['promotion']['service_id'], service['id'])

        with self.assertRaises(DomainError):
            self.command('record_inquiry', {
                'event_key': 'wrong-source', 'service_id': service['id'], 'publication_id': publication['id'],
                'source_type': 'manual', 'occurred_at': now(), 'problem_category': '来源检查', 'summary': '',
                'attribution': 'explicit', 'attribution_basis': '演示发布不能算真实咨询', 'validity': 'pending'})

        inquiry = self.command('record_inquiry', {
            'event_key': 'anonymous-1', 'service_id': service['id'], 'publication_id': publication['id'],
            'source_type': 'simulation',
            'occurred_at': now(), 'problem_category': '是否提供服装', 'summary': '询问是否需要自备服装',
            'attribution': 'explicit', 'attribution_basis': '咨询者说明看到该内容', 'validity': 'valid',
        })['inquiries'][0]
        state = self.command('record_inquiry', {
            'event_key': 'anonymous-2', 'service_id': service['id'], 'publication_id': None,
            'source_type': 'manual',
            'occurred_at': now(), 'problem_category': '是否提供服装', 'summary': '',
            'attribution': 'unknown', 'attribution_basis': '', 'validity': 'pending',
        })
        self.assertEqual(len(state['inquiries']), 2)
        with self.assertRaises(DomainError):
            self.command('record_inquiry', {
                'event_key': 'anonymous-2', 'service_id': service['id'], 'publication_id': None,
                'source_type': 'manual',
                'occurred_at': now(), 'problem_category': '重复', 'summary': '',
                'attribution': 'unknown', 'attribution_basis': '', 'validity': 'pending'})

        state = self.command('analyze_promotion', {
            'account_id': self.account['id'], 'service_id': service['id'],
            'source_type': 'simulation',
            'window_start': '2026-01-01T00:00:00+00:00', 'window_end': now(),
            'confirmed_complete': True, 'zero_confirmed': False,
        })
        analysis = state['promotion_analyses'][0]
        self.assertEqual(analysis['counts'], {'total': 1, 'explicit': 1, 'valid': 1, 'unknown': 0, 'multi_touch': 0})
        self.assertIn('是否提供服装', analysis['suggestion'])
        self.assertIn(inquiry['id'], analysis['inquiry_refs'])

        state = self.command('update_inquiry', {'id': inquiry['id'], 'validity': 'invalid', 'status': 'active'})
        self.assertEqual(state['promotion_analyses'][0]['status'], 'superseded')
        self.assertEqual(next(row for row in state['inquiries'] if row['id'] == inquiry['id'])['version'], 2)

    def test_unknown_is_not_zero_and_cross_owner_is_hidden(self):
        service = self.service()
        with self.assertRaises(DomainError):
            self.command('analyze_promotion', {
                'account_id': self.account['id'], 'service_id': service['id'],
                'source_type': 'manual',
                'window_start': '2026-01-01T00:00:00+00:00', 'window_end': now(),
                'confirmed_complete': False, 'zero_confirmed': True})
        state = self.command('analyze_promotion', {
            'account_id': self.account['id'], 'service_id': service['id'],
            'source_type': 'manual',
            'window_start': '2026-01-01T00:00:00+00:00', 'window_end': now(),
            'confirmed_complete': False, 'zero_confirmed': False})
        self.assertIn('缺失不能当作零咨询', state['promotion_analyses'][0]['suggestion'])
        with self.assertRaises(DomainError):
            self.command('update_inquiry', {'id': 'missing', 'validity': 'valid', 'status': 'active'}, owner='bob')

    def test_analysis_compares_instants_across_timezone_offsets(self):
        service = self.service()
        self.command('record_inquiry', {
            'event_key': 'timezone-offset', 'service_id': service['id'], 'publication_id': None,
            'source_type': 'manual', 'occurred_at': '2026-01-02T01:00:00+08:00',
            'problem_category': '时区测试', 'summary': '', 'attribution': 'unknown',
            'attribution_basis': '', 'validity': 'pending'})
        state = self.command('analyze_promotion', {
            'account_id': self.account['id'], 'service_id': service['id'], 'source_type': 'manual',
            'window_start': '2026-01-01T16:00:00+00:00', 'window_end': '2026-01-01T18:00:00+00:00',
            'confirmed_complete': True, 'zero_confirmed': False})
        self.assertEqual(state['promotion_analyses'][0]['counts']['total'], 1)


if __name__ == '__main__':
    unittest.main()
