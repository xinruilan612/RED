"""Reviewer selects exact draft text without lossy model retranscription."""
import copy
import unittest

from backend.contracts import DomainError
from backend.live import messages_for, normalize, schema
from backend.review_passages import bind, passages
from backend.workflow import Run


class ReviewPassageTests(unittest.TestCase):
    def fixture(self):
        run=Run('owner','snapshot',context={'mode':'live','material':'产品具有电源开关。','topic':'鼠标','audience':'学生','tone':'朴实','allow_hypothesis':False})
        run.start()
        run.branch('audience','snapshot','succeeded',{'sample_size':0})
        run.branch('research','snapshot','succeeded',{'core_gap':False})
        run.join(True)
        run.draft({'selected_title':'鼠标选择','body':'它有电源开关。\n电池供电，注意适用条件！','cta':'你的选择？','tags':['鼠标']})
        return run

    def entry(self,run):
        passage=next(p for p in passages(run.drafts[-1]['content']) if p['text']=='它有电源开关。')
        return {'draft_excerpt_id':passage['id'],'source_id':'user-material','quote':'产品具有电源开关。'}

    def test_catalog_exact_text_stable_and_version_bound(self):
        content=self.fixture().drafts[-1]['content'];before=copy.deepcopy(content)
        catalog=passages(content)
        self.assertEqual(catalog,passages(content))
        self.assertEqual(len({p['id'] for p in catalog}),len(catalog))
        for p in catalog:
            field=content[p['location']]
            self.assertTrue(any(p['text'] in s for s in field) if isinstance(field,list) else p['text'] in field)
        content2=copy.deepcopy(content);content2['cta']='另一问题'
        self.assertFalse({p['id'] for p in catalog}&{p['id'] for p in passages(content2)})
        self.assertEqual(content,before)

    def test_prompt_supplies_exact_catalog_only_to_reviewer(self):
        run=self.fixture();before=copy.deepcopy(run.__dict__)
        messages,data=messages_for(run,'review')
        self.assertEqual(data['draft_passages'],passages(run.drafts[-1]['content']))
        self.assertIn('draft_excerpt_id/source_id/quote',messages[0]['content'])
        self.assertNotIn('draft_passages',messages_for(run,'revise')[1])
        self.assertEqual(run.__dict__,before)

    def test_id_binds_exact_text_and_preserves_raw_model_response(self):
        run=self.fixture();raw=schema('review');entry=self.entry(run)
        # Model source wording differs from the draft; explicit ID is authority.
        entry['excerpt']='它具有电源开关。';raw['claim_map']=[entry];before=copy.deepcopy(raw)
        report=normalize(run,'review',raw)
        self.assertEqual(report['claim_map'][0]['excerpt'],'它有电源开关。')
        self.assertEqual(report['claim_map'][0]['draft_excerpt_id'],entry['draft_excerpt_id'])
        self.assertEqual(report['decision'],'approved')
        self.assertEqual(raw,before)
        self.assertIsNone(run.accepted_ref)

    def test_id_without_excerpt_works(self):
        run=self.fixture();raw=schema('review');raw['claim_map']=[self.entry(run)]
        self.assertEqual(normalize(run,'review',raw)['claim_map'][0]['excerpt'],'它有电源开关。')

    def test_unknown_invalid_and_stale_ids_rejected_even_with_valid_excerpt(self):
        run=self.fixture();old=self.entry(run)['draft_excerpt_id']
        run.drafts[-1]['content']['cta']='修改了互动'
        for bad in ('dp-unknown',None,3,[],{},old):
            with self.subTest(bad=bad):
                raw=schema('review');raw['claim_map']=[dict(self.entry(run),draft_excerpt_id=bad,excerpt='它有电源开关。')]
                with self.assertRaises(DomainError):normalize(run,'review',raw)

    def test_source_id_and_quote_still_strict(self):
        run=self.fixture()
        for change in ({'source_id':'missing'},{'quote':'产品有电源开关。'}):
            raw=schema('review');raw['claim_map']=[self.entry(run)|change]
            with self.assertRaises(DomainError):normalize(run,'review',raw)

    def test_legacy_no_id_paraphrase_rejected_exact_excerpt_accepted(self):
        run=self.fixture();raw=schema('review')
        raw['claim_map']=[{'excerpt':'它具有电源开关。','source_id':'user-material','quote':'产品具有电源开关。'}]
        with self.assertRaises(DomainError):normalize(run,'review',raw)
        raw['claim_map'][0]['excerpt']='它有电源开关。'
        self.assertEqual(normalize(run,'review',raw)['claim_map'],raw['claim_map'])

    def test_binding_does_not_resolve_issues_or_change_decision(self):
        run=self.fixture();raw=schema('review')
        raw.update(decision='needs_human',next_action='request_human',human_questions=['请补充续航证据'])
        raw['claim_map']=[self.entry(run)]
        result=bind(raw,run.drafts[-1]['content'])
        for key in ('decision','next_action','issues','checks','human_questions'):
            self.assertEqual(result[key],raw[key])
        self.assertEqual(normalize(run,'review',raw)['decision'],'needs_human')

    def test_one_passage_can_bind_separate_source_facts(self):
        run=self.fixture();raw=schema('review');raw['claim_map']=[self.entry(run),self.entry(run)]
        report=normalize(run,'review',raw)
        self.assertEqual(len(report['claim_map']),2)
        self.assertEqual(report['claim_map'][0]['excerpt'],report['claim_map'][1]['excerpt'])

    def test_issue_id_binds_location_and_excerpt_without_changing_judgment(self):
        run=self.fixture();content=run.drafts[-1]['content']
        passage=next(p for p in passages(content) if p['location']=='tags')
        issue={'issue_id':'i1','draft_excerpt_id':passage['id'],'location':'body',
               'excerpt':'旧版不存在的标签','severity':'major','state':'open',
               'reason':'标签过泛','suggestion':'使用具体标签'}
        raw={'decision':'revision_required','next_action':'revise','issues':[issue]}
        before=copy.deepcopy(raw)
        result=bind(raw,content)
        self.assertEqual(result['issues'][0],issue|{'location':'tags','excerpt':'鼠标'})
        self.assertEqual(result['decision'],'revision_required')
        self.assertEqual(result['next_action'],'revise')
        self.assertEqual(raw,before)

    def test_issue_ids_checked_even_without_claim_map(self):
        run=self.fixture();content=run.drafts[-1]['content'];old=passages(content)[0]['id']
        content['cta']='已修改的互动'
        for bad in ('unknown',None,7,[],{},old):
            with self.subTest(bad=bad):
                raw={'issues':[{'draft_excerpt_id':bad,'location':'selected_title','excerpt':'鼠标选择'}]}
                with self.assertRaises(DomainError):bind(raw,content)

    def test_legacy_issues_are_not_silently_rewritten(self):
        content=self.fixture().drafts[-1]['content']
        raw={'issues':[{'location':'body','excerpt':'旧稿原句','reason':'原意见'}]}
        self.assertEqual(bind(raw,content),raw)

    def test_issue_id_only_normalizes_before_required_text_validation(self):
        run=self.fixture();raw=schema('review');entry=self.entry(run)
        raw['claim_map']=[entry]
        raw.update(decision='revision_required',next_action='revise')
        raw['issues']=[{'issue_id':'i1','draft_excerpt_id':entry['draft_excerpt_id'],
                        'severity':'major','state':'open','reason':'句子没有说明使用场景',
                        'suggestion':'补充开关的使用场景'}]
        before=copy.deepcopy(raw)
        report=normalize(run,'review',raw)
        self.assertEqual(report['issues'][0]['excerpt'],'它有电源开关。')
        self.assertEqual(report['issues'][0]['location'],'body')
        self.assertEqual(report['issues'][0]['severity'],'major')
        self.assertEqual(report['issues'][0]['state'],'open')
        self.assertEqual(report['decision'],'revision_required')
        self.assertEqual(raw,before)
