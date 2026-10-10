"""Offline tests for the explicitly bounded personal-account research probe."""
import json
from pathlib import Path
import tempfile
import unittest
from scripts.mediacrawler_probe import profile_id,clean_note,clean_comments,private_json,ProbeStopped

class MediaCrawlerProbeTests(unittest.TestCase):
    def test_profile_scope_rejects_other_hosts_credentials_and_paths(self):
        owner='a'*24
        self.assertEqual(profile_id('https://www.xiaohongshu.com/user/profile/'+owner),owner)
        for value in ('http://www.xiaohongshu.com/user/profile/'+owner,'https://evil.test/user/profile/'+owner,
                      'https://user@www.xiaohongshu.com/user/profile/'+owner,'https://www.xiaohongshu.com/explore/'+owner):
            with self.assertRaises(ValueError):profile_id(value)
    def test_note_owner_is_checked_and_secrets_and_missing_metrics_are_not_fabricated(self):
        raw={'user':{'user_id':'owner'},'note_id':'note','xsec_token':'secret','interact_info':{'liked_count':'0'}}
        result=clean_note(raw,'owner')
        self.assertNotIn('secret',json.dumps(result));self.assertIsNone(result['views']);self.assertIsNone(result['metrics']['comment_count'])
        self.assertEqual(result['metrics']['liked_count'],'0')
        with self.assertRaises(ProbeStopped):clean_note(raw,'other')
    def test_comment_limit_dedup_and_metadata_minimization(self):
        rows=[{'id':str(i),'content':'text','user_info':{'phone':'private'},'sub_comments':[{'content':'not requested'}]} for i in range(35)]
        result=clean_comments([rows[0],*rows])
        self.assertEqual(len(result),20);self.assertEqual(len({r['id'] for r in result}),20)
        self.assertNotIn('private',json.dumps(result));self.assertNotIn('sub_comments',json.dumps(result))
    def test_result_file_is_private(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'result.json';private_json(path,{'status':'done'})
            self.assertEqual(path.stat().st_mode&0o777,0o600)
            self.assertEqual(json.loads(path.read_text())['status'],'done')
