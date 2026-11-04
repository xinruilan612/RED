"""Live repair controls: researcher-abbreviated gaps, never creator manuscripts.

Reuse the original five-CNY ledger; reference answers are evaluation data and
are never supplied to the editing model. No paid calls without authorization.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.run_windtunnel_agent_study import StudyRunner, section, sha

INPUTS = ROOT / 'docs/windtunnel/agent_study/revision3/probe_inputs.json'
PUBLIC = ROOT / 'docs/windtunnel/public_samples'
IDS = ('S06', 'S07', 'S10')
LABEL = '人为删节缺口控制，非真实创作者'


def load_inputs(path=INPUTS):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if data.get('classification') != LABEL or data.get('revision') != 'v3.controlled':
        raise ValueError('Controlled probes must retain their explicit artificial-gap label')
    rubric = ROOT / data['rubric_path']
    if sha(rubric.read_bytes()) != data['rubric_sha256']:
        raise ValueError('Frozen task rubric changed')
    original_tasks = {t['sample_id']: t for t in json.loads(rubric.read_text())['tasks']}
    if tuple(c['sample_id'] for c in data['cases']) != IDS:
        raise ValueError('Expected exactly three declared repair controls')
    for case in data['cases']:
        if case['classification'] != LABEL or case['task'] != original_tasks[case['sample_id']]:
            raise ValueError('Control label or original task changed')
        for key, hash_key in (('draft_path', 'draft_sha256'),
                              ('support_path', 'support_sha256'),
                              ('source_original_draft_path', 'source_original_sha256')):
            if sha((PUBLIC / case[key]).read_bytes()) != case[hash_key]:
                raise ValueError('Controlled input or source hash changed')
        if sha(section(PUBLIC / case['source_original_draft_path'])) != case['source_original_section_sha256']:
            raise ValueError('Original source section changed')
        for key in ('license_ref', 'code_license_ref'):
            if not (ROOT / case['license_directory'] / case[key]).is_file():
                raise ValueError('Source license missing')
    return data


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--budget-ledger', type=Path, required=True,
                        help='Existing cumulative original study ledger, never a new budget')
    parser.add_argument('--authorize-live', action='store_true')
    parser.add_argument('--revision', default='v4.controlled')
    args = parser.parse_args(argv)
    if not args.authorize_live:
        parser.error('explicit live authorization required; cumulative maximum 5 CNY')
    if not args.budget_ledger.is_file():
        parser.error('original cumulative budget ledger must already exist')
    data = load_inputs()
    runner = StudyRunner(args.workspace, budget_ledger=args.budget_ledger,
                         continue_after_unknown=True, atomic_conditions=False,
                         revision=args.revision)
    # Preserve original official support paths; only the declared manuscript
    # is deliberately shortened. Reference answers remain outside model input.
    runner.samples = {case['sample_id']: dict(runner.samples[case['sample_id']],
                      draft_path=case['draft_path'], draft_sha256=case['draft_sha256'],
                      draft_kind='researcher_abbreviated_gap_control',
                      adaptation=LABEL, deletion_design=case['deletion_design'])
                      for case in data['cases']}
    runner.tasks = {case['sample_id']: case['task'] for case in data['cases']}
    runner.freeze()
    for sample_id in IDS:
        for method in ('baseline', 'windtunnel'):
            runner.run_case(sample_id, method)
    print(json.dumps(runner.client.summary(), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
