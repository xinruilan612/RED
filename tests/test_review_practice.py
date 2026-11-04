import csv
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from scripts.build_review_practice import build


class PracticePackageTests(unittest.TestCase):
    def test_reviewer_zip_contains_blank_scores_and_no_private_mapping(self):
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp)/'practice'
            data={'controls':{'scope':'practice_only'},'tasks':[{'task_id':'fixture-task','brief':'controlled fixture',
                  'articles':[{'group':g,'text':'Controlled fixture article.'} for g in 'ABCD']} ]}
            result=build(data,out)
            self.assertEqual(result['articles'],4)
            self.assertTrue((out/'researcher-private/mapping.json').is_file())
            for archive in out.glob('*.zip'):
                with zipfile.ZipFile(archive) as package:
                    self.assertNotIn('mapping.json',package.namelist())
                    page=package.read('articles.html').decode()
                    self.assertIn('下载我的评分CSV',page)
                    self.assertNotIn('"group":',page)
                    rows=list(csv.DictReader(package.read('scores.csv').decode('utf-8-sig').splitlines()))
                    self.assertEqual(len(rows),4)
                    self.assertTrue(all(row['factuality']=='' for row in rows))

    def test_missing_preregistered_article_rejected_without_fabrication(self):
        with tempfile.TemporaryDirectory() as temp:
            data={'tasks':[{'task_id':'fixture','articles':[{'group':g,'text':'fixture'} for g in 'ABC']} ]}
            with self.assertRaises(ValueError):build(data,Path(temp)/'bad')
            self.assertFalse((Path(temp)/'bad').exists())
