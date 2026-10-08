"""A three-reader pilot must preserve incomplete real response collection."""
from copy import deepcopy
import tempfile
import unittest
from pathlib import Path
from scripts.brand_blindtest import generate, summarize, normalize_response_identity, DIMENSIONS

class DayOneReadersTests(unittest.TestCase):
    def test_three_files_balanced_and_two_responses_do_not_impute_third(self):
        case={'product':'鼠标','audience':'学生','goal':'了解','facts':['USB接收器'],'sources':[{'title':'来源','url':'https://example.com'}],'constraints':['不虚构']}
        with tempfile.TemporaryDirectory() as folder:
            mapping=generate(case,'普通真实稿','系统真实稿',folder,count=3,seed=21)
            self.assertEqual(sorted(p.name for p in Path(folder).glob('*.html')),['P01-试读.html','P02-试读.html','P03-试读.html'])
            self.assertIn(sum(p['labels']['A']=='system' for p in mapping['participants'].values()),(1,2))
            responses=[]
            for pid in ('P01','P02'):
                answers={'preference':'tie','preference_reason':'测试占位，仅用于单元测试'}
                for label in ('A','B'):
                    answers.update({label+'_'+key:'3' for key in DIMENSIONS})
                    answers.update({label+'_message':'测试回答',label+'_reason':'测试理由'})
                responses.append({'participant':pid,'draft_hashes':mapping['participants'][pid]['draft_hashes'],'answers':answers})
            result=summarize(mapping,responses)
            self.assertEqual(result['sample_size'],2)
            self.assertEqual(result['missing_participants'],['P03'])
            self.assertEqual(len(result['scores']['system']['interest']),2)
            self.assertEqual(summarize(mapping,[])['sample_size'],0)


class ResponseIdentityTests(unittest.TestCase):
    def setUp(self):
        self.hashes = {'A': 'ordinary-hash', 'B': 'system-hash'}
        self.mapping = {'participants': {
            pid: {'draft_hashes': deepcopy(self.hashes)}
            for pid in ('P02', 'P03')
        }}
        self.response = {
            'participant': 'P02', 'draft_hashes': deepcopy(self.hashes),
            'answers': {'A_credible': '1', 'A_reason': '保留原始回答'},
            'submitted_at': '2026-10-08T09:04:35.296Z',
        }

    def test_confirmed_identity_copy_preserves_answers_and_audit(self):
        before = deepcopy(self.response)
        mapping_before = deepcopy(self.mapping)
        reason = '用户确认：第三位独立读者误用了问卷，不知道稿件来源。'
        normalized, audit = normalize_response_identity(
            self.mapping, self.response, 'P03', reason)
        self.assertEqual(normalized, {**before, 'participant': 'P03'})
        self.assertEqual(audit, {'original_participant': 'P02',
                               'target_participant': 'P03',
                               'confirmation': reason})
        normalized['answers']['A_credible'] = '5'
        normalized['draft_hashes']['A'] = 'changed'
        self.assertEqual(self.response, before)
        self.assertEqual(self.mapping, mapping_before)

    def test_unknown_or_same_identity_rejected(self):
        for original, target in (('P99', 'P03'), ('P02', 'P99'),
                                 ('P02', 'P02'), (None, 'P03'),
                                 ('P02', [])):
            with self.subTest(original=original, target=target):
                response = {**self.response, 'participant': original}
                with self.assertRaises(ValueError):
                    normalize_response_identity(self.mapping, response, target, '已确认')

    def test_missing_confirmation_rejected(self):
        for confirmation in ('', '  \n', None, True, {'reason': '确认'}):
            with self.subTest(confirmation=confirmation):
                with self.assertRaises(ValueError):
                    normalize_response_identity(self.mapping, self.response, 'P03', confirmation)

    def test_target_hash_or_order_mismatch_rejected(self):
        for hashes in ({'A': 'changed', 'B': 'system-hash'},
                       {'A': 'system-hash', 'B': 'ordinary-hash'},
                       {'A': 'ordinary-hash'}, None):
            with self.subTest(hashes=hashes):
                response = {**self.response, 'draft_hashes': hashes}
                with self.assertRaises(ValueError):
                    normalize_response_identity(self.mapping, response, 'P03', '已确认')
        self.assertEqual(self.response['participant'], 'P02')

    def test_summarize_still_rejects_duplicate_original_identity(self):
        mapping = deepcopy(self.mapping)
        mapping['participants']['P02']['labels'] = {'A': 'ordinary_ai', 'B': 'system'}
        response = deepcopy(self.response)
        response['answers'] = {'preference': 'tie', 'preference_reason': '单元测试'}
        for label in ('A', 'B'):
            response['answers'].update({label + '_' + key: '3' for key in DIMENSIONS})
            response['answers'].update({label + '_message': '测试回答', label + '_reason': '测试理由'})
        with self.assertRaisesRegex(ValueError, '重复'):
            summarize(mapping, [response, deepcopy(response)])
