"""Validate source/diagram consistency and proposal constraints, not product behavior."""
import importlib.util
import json
import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESIGN = ROOT / 'docs/design'
spec = importlib.util.spec_from_file_location('atlas', ROOT / 'scripts/build_design_atlas.py')
atlas = importlib.util.module_from_spec(spec)
spec.loader.exec_module(atlas)


class DesignDocumentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads((DESIGN/'design_contract.json').read_text())

    def test_local_links_resolve(self):
        for path in [ROOT/'AGENTS.md', *ROOT.glob('docs/**/*.md')]:
            for dest in re.findall(r'\]\(([^)]+)\)', path.read_text()):
                if '://' in dest or dest.startswith('#'):
                    continue
                with self.subTest(file=path.name, link=dest):
                    self.assertTrue((path.parent/dest.split('#')[0]).is_file())

    def test_states_known_and_terminals_absorbing(self):
        transitions = self.contract['transitions']
        for source, targets in transitions.items():
            self.assertEqual(len(targets), len(set(targets)))
            self.assertTrue(set(targets) <= transitions.keys())
            if source in self.contract['terminal_states']:
                self.assertEqual(targets, [])
        seen, pending = set(), ['QUEUED']
        while pending:
            state = pending.pop()
            if state not in seen:
                seen.add(state)
                pending.extend(transitions[state])
        self.assertEqual(seen, set(transitions))

    def test_lifecycle_mermaid_contains_every_transition(self):
        text = (DESIGN/'diagrams/lifecycle.mmd').read_text()
        pairs = set(re.findall(r'^\s*(\w+)\s+(?:-->|-\.->)(?:\|[^\n]+?\|)?\s*(\w+)\s*$',text,re.M))
        expected = {(a,b) for a,bs in self.contract['transitions'].items() for b in bs}
        self.assertEqual(pairs, expected)

    def test_parameter_invariants_and_paid_default(self):
        p = self.contract['parameters']
        self.assertLess(p['heartbeat_s']*2, p['lease_s'])
        self.assertLess(p['model_timeout_s'], p['run_active_timeout_s'])
        self.assertLessEqual(p['pages_min'], p['pages_default'])
        self.assertLessEqual(p['pages_default'], p['pages_max'])
        self.assertLess(p['output_tokens_max'], p['run_tokens_max'])
        self.assertFalse(p['paid_provider_enabled'])
        self.assertIsNone(p['run_currency_budget'])
        self.assertIsNone(p['user_daily_currency_budget'])

    def test_diagrams_current_valid_and_in_bounds(self):
        for graph in atlas.GRAPHS:
            with self.subTest(graph=graph['id']):
                nodes={n['id']:n for n in graph['nodes']}
                self.assertEqual(len(nodes),len(graph['nodes']))
                for n in nodes.values():
                    self.assertGreaterEqual(n['x'],0)
                    self.assertGreaterEqual(n['y'],0)
                    self.assertLessEqual(n['x']+n['w'],graph['width'])
                    self.assertLessEqual(n['y']+atlas.H,graph['height']-65)
                for edge in graph['edges']:
                    self.assertIn(edge['source'],nodes)
                    self.assertIn(edge['target'],nodes)
                    for x,y in edge['points']:
                        self.assertTrue(0<=x<=graph['width'] and 0<=y<=graph['height'])
                svg=(DESIGN/'diagrams'/f'{graph["id"]}.svg').read_text()
                self.assertEqual(svg,atlas.svg(graph))
                self.assertEqual((DESIGN/'diagrams'/f'{graph["id"]}.mmd').read_text(),atlas.mermaid(graph))
                root=ET.fromstring(svg)
                self.assertIsNotNone(root.find('{http://www.w3.org/2000/svg}title'))

    def test_modules_and_agents_documented(self):
        text=(DESIGN/'MODULES.md').read_text()
        for value in self.contract['agents']+self.contract['modules']:
            self.assertIn(value,text)

    def test_atlas_offline(self):
        text=(DESIGN/'DESIGN_ATLAS.html').read_text()
        self.assertNotRegex(text,r'<script|<link[^>]*https?://|<img[^>]*https?://')
        self.assertEqual(text.count('<svg '),len(atlas.GRAPHS))
        for g in atlas.GRAPHS:
            self.assertIn(atlas.svg(g),text)

    def test_five_layers_and_four_agents_are_unambiguous(self):
        c = self.contract
        self.assertEqual(c['agents'], ['audience', 'research', 'content', 'reviewer'])
        self.assertEqual(list(c['layers']), ['L1', 'L2', 'L3', 'L4', 'L5'])
        self.assertEqual(set(c['layers']['L3']), set(c['agents']))
        located = [m for layer in c['layers'].values() for m in layer if m.startswith('M')]
        located += c['cross_cutting_modules']
        self.assertCountEqual(located, c['modules'])
        self.assertEqual(c['content_stages'], ['strategy', 'outline', 'hook', 'title', 'body'])

    def test_workflow_diagram_matches_routing_contract(self):
        graph = next(g for g in atlas.GRAPHS if g['id'] == 'workflow')
        expected = {(a,b) for a,bs in self.contract['workflow'].items() for b in bs}
        actual = {(e['source'],e['target']) for e in graph['edges']}
        self.assertEqual(actual, expected)
        self.assertEqual({n['id'] for n in graph['nodes']}, set(self.contract['workflow']))
        self.assertEqual(self.contract['join_requires'], ['audience', 'research'])
        predecessors = {a for a,bs in self.contract['workflow'].items() if 'join' in bs}
        self.assertEqual(predecessors, set(self.contract['join_requires']))

    def test_revision_cannot_bypass_review_or_human_acceptance(self):
        flow = self.contract['workflow']
        self.assertEqual(flow['revise'], ['content'])
        self.assertEqual(flow['content'], ['reviewer'])
        # Removing either gate must make final content unreachable from revision.
        for blocked in ('reviewer', 'human'):
            pending, seen = ['revise'], set()
            while pending:
                node = pending.pop()
                if node in seen or node == blocked:
                    continue
                seen.add(node)
                pending.extend(flow[node])
            self.assertNotIn('final', seen)
        self.assertNotIn('human', flow['limit'])
        self.assertNotIn('final', flow['limit'])

    def test_tool_privileges_and_quality_limits(self):
        tools = self.contract['tool_permissions']
        self.assertEqual(set(tools), set(self.contract['agents']))
        for granted in tools.values():
            self.assertNotIn('export_bundle', granted)
        p = self.contract['parameters']
        self.assertGreaterEqual(p['run_attempts_max'], 2 + len(self.contract['content_stages']) + 1)
        self.assertLessEqual(p['agent_tool_calls_max'], p['run_tool_calls_max'])
        self.assertFalse(self.contract['review_policy']['score_gate'])

    def test_research_provenance_and_no_execution_claim(self):
        rows=json.loads((ROOT/'docs/research/repository_snapshot.json').read_text())
        text=(ROOT/'docs/research/GITHUB_PROJECTS.md').read_text()
        self.assertEqual(len(rows),5)
        for row in rows:
            self.assertIn(row['url'],text)
            self.assertEqual(row['observed_at'],'2026-09-20')
        self.assertIn('未安装、运行',text)
        self.assertIn('CC BY-NC-SA',text)
        self.assertIn('404',text)


if __name__=='__main__':
    unittest.main()
