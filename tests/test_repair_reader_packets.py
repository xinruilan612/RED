import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from scripts import prepare_repair_readers as packets
from scripts.run_windtunnel_agent_study import section, sha, write_json


class RepairReaderPacketTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.controls = self.root / 'controls'
        self.destination = self.root / 'anonymous'
        self.inputs = packets.load_inputs()
        for case in self.inputs['cases']:
            sid = case['sample_id']
            folder = self.controls / 'cases' / sid / 'windtunnel'
            folder.mkdir(parents=True)
            original = section(packets.PUBLIC / case['draft_path'])
            final = original + '\nFixture supported repair for testing packet hashes only.'
            (folder / 'final.txt').write_text(final)
            write_json(folder / 'result.json', dict(sample_id=sid, method='windtunnel', outcome='completed',
                original_sha256=sha(original), final_sha256=sha(final),
                effective_repair_confirmed=False, unresolved_conditions=['fixture']))

    def test_six_fresh_packets_balanced_variants_three_tasks_no_answers(self):
        packets.prepare(self.controls, self.destination, seed=17)
        key = json.loads((self.destination / 'assignment_key_RESEARCHER_ONLY.json').read_text())['assignments']
        self.assertEqual(len(key), 18)
        self.assertEqual(len({r['blind_id'] for r in key}), 18)
        counts = Counter((r['sample_id'], r['variant']) for r in key)
        self.assertEqual(set(counts.values()), {3})
        self.assertEqual(len(counts), 6)
        for reader in (f'R{i:02}' for i in range(1, 7)):
            entries = [r for r in key if r['reader_id'] == reader]
            self.assertEqual({r['sample_id'] for r in entries}, set(packets.IDS))
            folder = self.destination / 'readers' / reader
            self.assertEqual(len(list(folder.glob('*.txt'))), 3)
            tasks = json.loads((folder / 'tasks.json').read_text())
            self.assertEqual(len(tasks['tasks']), 3)
            self.assertEqual([t['reading_order'] for t in tasks['tasks']], [1, 2, 3])
            self.assertIsNone(tasks['human_reading_seconds'])
            raw = (folder / 'tasks.json').read_text()
            for forbidden in ('expected_answer', 'sample_id', '"variant":', 'windtunnel_final', 'abbreviated_control'):
                self.assertNotIn(forbidden, raw)
            for task in tasks['tasks']:
                text = Path(task['manuscript_path']).read_text()
                self.assertEqual(sha(text), task['manuscript_sha256'])
                self.assertEqual(Path(task['manuscript_path']).parent, folder.resolve())
            template = json.loads((folder / 'response_template.json').read_text())
            self.assertIsNone(template['human_reading_seconds'])
            for response in template['responses']:
                self.assertEqual([p['point'] for p in response['points']], [1, 2, 3, 4, 5])
                self.assertTrue(all(set(p) == {'point', 'answer_text', 'evidence', 'missing_information'} for p in response['points']))

    def test_freeze_records_source_result_rubric_and_all_packet_hashes(self):
        packets.prepare(self.controls, self.destination, seed=42)
        frozen = json.loads((self.destination / 'freeze_RESEARCHER_ONLY.json').read_text())
        self.assertEqual(frozen['human_participants'], 0)
        self.assertEqual(frozen['rubric_sha256'], self.inputs['rubric_sha256'])
        self.assertEqual(frozen['probe_inputs_sha256'], sha(packets.INPUTS.read_bytes()))
        self.assertEqual(len(frozen['case_audit']), 3)
        self.assertIn('assignment_key_RESEARCHER_ONLY.json', frozen['packet_hashes'])
        for path, digest in frozen['packet_hashes'].items():
            self.assertEqual(sha((self.destination / path).read_bytes()), digest)
        for case in frozen['case_audit']:
            self.assertEqual(sha(Path(case['result_path']).read_bytes()), case['result_file_sha256'])
            self.assertFalse(case['effective_repair_confirmed'])

    def test_missing_failed_or_hash_mismatched_cases_never_make_packets(self):
        result = self.controls / 'cases/S06/windtunnel/result.json'
        original = json.loads(result.read_text())
        bad_values = ({**original, 'outcome': 'failed'},
                      {**original, 'final_sha256': 'bad'},
                      {**original, 'original_sha256': 'bad'},
                      {**original, 'sample_id': 'S10'},
                      {**original, 'method': 'baseline'})
        for bad in bad_values:
            write_json(result, bad)
            with self.assertRaises(ValueError):
                packets.prepare(self.controls, self.destination, seed=1)
            self.assertFalse(self.destination.exists())
        result.unlink()
        with self.assertRaises(ValueError):
            packets.prepare(self.controls, self.destination, seed=1)
        self.assertFalse(self.destination.exists())

    def test_existing_packets_cannot_be_overwritten(self):
        packets.prepare(self.controls, self.destination, seed=1)
        before = (self.destination / 'assignment_key_RESEARCHER_ONLY.json').read_bytes()
        with self.assertRaises(ValueError):
            packets.prepare(self.controls, self.destination, seed=2)
        self.assertEqual((self.destination / 'assignment_key_RESEARCHER_ONLY.json').read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
