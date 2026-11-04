"""Execute the collector's DOM projection against instrumented, offline cards."""
import json
import subprocess
import unittest
from scripts.xhs_creator_reader import NOTE_CARDS_EXTRACT


class CreatorVisibilityTests(unittest.TestCase):
    def test_private_card_is_filtered_before_any_title_or_id_read(self):
        script='''
const extract=eval('('+JSON.parse(require('fs').readFileSync(0,'utf8'))+')');
const hidden={innerText:'私密标题 仅自己可见',getAttribute(){throw Error('private id read');},querySelector(){throw Error('private title read');},querySelectorAll(){throw Error('private metrics read');}};
const published={innerText:'公开帖子',getAttribute(){return JSON.stringify({noteTarget:{value:{noteId:'public'}}});},querySelector(sel){return {innerText:sel.includes('title')?'公开帖子':'2026-10-10'};},querySelectorAll(){return [];}};
const notes=extract([hidden,published]);
if(notes.length!==1||notes[0].id!=='public'||notes[0].visibility!=='public'||notes[0].visibility_source!=='creator_note_card_no_private_label')throw Error('wrong projection');
process.stdout.write(JSON.stringify(notes));
'''
        result=subprocess.run(['node','-e',script],input=json.dumps(NOTE_CARDS_EXTRACT),text=True,capture_output=True,check=True)
        self.assertNotIn('私密标题',result.stdout)
        self.assertEqual(json.loads(result.stdout)[0]['title'],'公开帖子')
