"""Validate fixture integrity only; never turn empty human forms into evidence."""
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path


def validate():
    directory = Path(__file__).resolve().parent
    app = next(p for p in directory.parents if (p/'backend').is_dir())
    root = app.parent
    human = root/'output/冲刺提升验收-20261102/真人验收'
    load = lambda path: json.loads(path.read_text(encoding='utf-8'))
    tasks = load(directory/'20tasks.json')['items']
    sources = load(directory/'sources.json')['items']
    source_map = {s['source_id']: s for s in sources}
    answers = load(directory/'fixed_answers.json')['items']
    assert len(tasks) == len(sources) == len(answers) == 20
    assert len({t['id'] for t in tasks}) == 20
    assert Counter(t['category'] for t in tasks) == {'digital': 7, 'home': 7, 'study': 6}
    assert sum(s['provenance']['kind'] == 'existing_project_fictional_fixture' for s in sources) == 3
    span_count = 0
    for source in sources:
        assert hashlib.sha256(source['text'].encode()).hexdigest() == source['text_sha256']
        origin = source['provenance']
        container = app/origin['path']
        assert container.is_file()
        if origin.get('container_sha256'):
            assert hashlib.sha256(container.read_bytes()).hexdigest() == origin['container_sha256']
        node = load(container)
        for part in origin['json_pointer'].strip('/').split('/'):
            node = node[int(part)] if isinstance(node, list) else node[part]
        assert node == source['text']
    for task, answer in zip(tasks, answers):
        assert task['is_real_user_task'] is False
        example = task['reference_example']
        assert hashlib.sha256(example['text'].encode()).hexdigest() == example['text_sha256']
        assert example['classification']['domains'] == [task['domain']]
        assert example['classification']['material_type'] == 'example'
        assert task['gold_status'] == 'proposed_pending_two_human_reviewers'
        assert task['input']['material'] == task['material']
        assert task['input']['creation']['word_count'] == 300
        assert task['input']['web_research']['enabled'] is False
        assert task['id'] == answer['task_id']
        assert task['answer'] == answer['fixed_answer']
        assert answer['cost_seconds'] is None and answer['self_reported_burden'] is None
        for span in task['facts'] + [s for req in task['proposed_requirements'] for s in req['support']]:
            source = source_map[span['source_id']]
            assert source['text'][span['start']:span['end']] == span['quote']
            assert span['unit'] == 'unicode_codepoint'
            span_count += 1
    samples = load(directory/'30structure_samples.json')['items']
    assert len(samples) == 30
    assert Counter(s['category'] for s in samples) == {'digital': 10, 'home': 10, 'study': 10}
    segment_count = 0
    for sample in samples:
        text = (directory/sample['text_path']).read_text()
        assert hashlib.sha256(text.encode()).hexdigest() == sample['text_sha256']
        assert sample['gold_labels'] is None
        for segment in sample['paragraphs']:
            assert text[segment['start']:segment['end']] == segment['text']
            segment_count += 1
    assignments = load(directory/'blind_assignment_PRIVATE.json')['items']
    assert len(assignments) == 100
    assert len({a['article_id'] for a in assignments}) == 100
    for task in tasks:
        assert {a['private_arm'] for a in assignments if a['task_id'] == task['id']} == set('ABCDE')
    assert all(a['generation_status'] == 'not_generated' and a['output_path'] is None
               and a['output_sha256'] is None for a in assignments)
    csv_files = list(human.glob('*.csv'))
    for path in csv_files:
        with path.open(encoding='utf-8-sig', newline='') as handle:
            rows = list(csv.reader(handle))
        assert rows and len(set(rows[0])) == len(rows[0]), path.name
        assert all(len(row) == len(rows[0]) for row in rows[1:]), path.name
        if path.name.startswith('盲评-R'):
            assert len(rows) == 101
            assert all(not any(row[3:]) for row in rows[1:]), 'Unexpected human scores: '+path.name
        if path.name.startswith('结构标注-标注者'):
            assert len(rows) == segment_count + 1
            assert all(not any(row[6:]) for row in rows[1:]), 'Unexpected human annotations'
        if path.name == '创作者招募与授权-空表.csv':
            assert len(rows) == 13
            assert all(not any(row[1:]) for row in rows[1:]), 'Unexpected human consent'
    return {'status': 'PASS', 'scope': 'fixture shape, counts, hashes, Unicode spans and empty human fields only',
            'task_count': len(tasks), 'source_count': len(sources), 'existing_fixture_sources': 3,
            'new_fictional_sources': 17, 'checked_spans': span_count,
            'structure_articles': len(samples), 'annotation_segments': segment_count,
            'blind_article_placeholders': len(assignments), 'csv_templates': len(csv_files),
            'actual_human_ratings': 0, 'actual_creator_feedback': 0, 'paid_model_calls': 0}


if __name__ == '__main__':
    print(json.dumps(validate(), ensure_ascii=False, indent=2))
