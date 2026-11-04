"""Prepare free anonymous Codex-reader packets for deliberate gap controls.

No model calls, no project agents, no human participants. Compare incomplete
controls with windtunnel final text; this does not compare against ordinary AI.
"""
import argparse
import json
import random
import secrets
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.run_windtunnel_agent_study import section, sha, write_json
from scripts.run_windtunnel_repair_probe import load_inputs, INPUTS, PUBLIC, IDS


def prepare(controls, destination, *, seed=None):
    controls, destination = Path(controls), Path(destination)
    if destination.exists():
        raise ValueError('Reader packets already exist; refusing overwrite')
    data = load_inputs()
    texts, audit = {}, []
    for case in data['cases']:
        sid = case['sample_id']
        original = section(PUBLIC / case['draft_path'])
        folder = controls / 'cases' / sid / 'windtunnel'
        result_path, final_path = folder / 'result.json', folder / 'final.txt'
        if not result_path.is_file() or not final_path.is_file():
            raise ValueError('All three windtunnel cases must exist before dispatch')
        result = json.loads(result_path.read_text(encoding='utf-8'))
        final = final_path.read_text(encoding='utf-8')
        if (result.get('outcome') != 'completed' or result.get('sample_id') != sid
                or result.get('method') != 'windtunnel'
                or result.get('original_sha256') != sha(original)
                or result.get('final_sha256') != sha(final)):
            raise ValueError('Incomplete case or mismatched manuscript/source hash')
        texts[(sid, 'abbreviated_control')] = original
        texts[(sid, 'windtunnel_final')] = final
        audit.append(dict(sample_id=sid, result_path=str(result_path.resolve()),
                          result_file_sha256=sha(result_path.read_bytes()),
                          original_sha256=sha(original), final_sha256=sha(final),
                          changed=original != final,
                          effective_repair_confirmed=result.get('effective_repair_confirmed'),
                          unresolved_conditions=result.get('unresolved_conditions')))
    seed = secrets.randbits(128) if seed is None else seed
    rng = random.Random(seed)
    readers = [f'R{i:02}' for i in range(1, 7)]
    assigned = {r: [] for r in readers}
    key = []
    for sid in IDS:
        order = readers[:]
        rng.shuffle(order)
        for index, reader in enumerate(order):
            variant = 'abbreviated_control' if index < 3 else 'windtunnel_final'
            blind_id = 'B' + f'{rng.getrandbits(128):032x}'
            assignment = dict(reader_id=reader, blind_id=blind_id, sample_id=sid,
                              variant=variant, manuscript_sha256=sha(texts[(sid, variant)]))
            key.append(assignment)
            assigned[reader].append(assignment)
    destination.parent.mkdir(parents=True, exist_ok=True)
    staged = Path(tempfile.mkdtemp(prefix='.repair-reader-packets-', dir=destination.parent))
    try:
        tasks_by_id = {c['sample_id']: c['task']['task_prompt'] for c in data['cases']}
        for reader in readers:
            folder = staged / 'readers' / reader
            rng.shuffle(assigned[reader])
            tasks, responses = [], []
            for index, entry in enumerate(assigned[reader], 1):
                blind_id = entry['blind_id']
                manuscript_name = blind_id + '.txt'
                folder.mkdir(parents=True, exist_ok=True)
                (folder / manuscript_name).write_text(texts[(entry['sample_id'], entry['variant'])], encoding='utf-8')
                tasks.append(dict(blind_id=blind_id, reading_order=index,
                                  task_prompt=tasks_by_id[entry['sample_id']],
                                  manuscript_path=str((destination / 'readers' / reader / manuscript_name).resolve()),
                                  manuscript_sha256=entry['manuscript_sha256']))
                responses.append(dict(blind_id=blind_id,
                    points=[dict(point=p, answer_text='', evidence=[], missing_information='') for p in range(1, 6)],
                    perceived_difficulty_1_to_5=None, open_feedback=''))
            write_json(folder / 'tasks.json', dict(reader_id=reader, participant_type='codex_proxy',
                human_reading_seconds=None,
                instruction='Only read your own tasks, manuscripts and response template. Do not search, execute code, read other files or use outside knowledge to fill gaps. Answer each of five points using exact short manuscript quotations; identify absent information. Do not guess workflow or variant. Save responses.json in this directory.',
                tasks=tasks))
            write_json(folder / 'response_template.json', dict(reader_id=reader,
                participant_type='codex_proxy', human_reading_seconds=None, responses=responses))
        write_json(staged / 'assignment_key_RESEARCHER_ONLY.json', dict(seed=seed, assignments=key))
        packet_hashes = {str(p.relative_to(staged)): sha(p.read_bytes())
                         for p in sorted(staged.rglob('*')) if p.is_file()}
        write_json(staged / 'freeze_RESEARCHER_ONLY.json', dict(
            participant_type='codex_proxy', human_participants=0,
            classification='人为删节缺口控制，非真实创作者',
            comparison='abbreviated_control versus windtunnel_final; not ordinary AI editing',
            shared_workspace_isolation='instruction only, no file permission isolation',
            controls_path=str(controls.resolve()), seed=seed,
            probe_inputs_sha256=sha(INPUTS.read_bytes()), rubric_sha256=data['rubric_sha256'],
            preparation_code_sha256=sha(Path(__file__).read_bytes()),
            case_audit=audit, packet_hashes=packet_hashes))
        if destination.exists():
            raise ValueError('Reader packet destination appeared; refusing overwrite')
        staged.rename(destination)
    finally:
        if staged.exists():
            shutil.rmtree(staged)
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--controls', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args(argv)
    print(prepare(args.controls, args.destination).resolve())


if __name__ == '__main__':
    main()
