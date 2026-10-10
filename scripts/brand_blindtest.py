"""Build offline blinded questionnaires from two existing drafts; no API calls."""
import argparse
from copy import deepcopy
import hashlib
import html
import json
import math
from pathlib import Path
import random
import secrets

DIMENSIONS = {"understand": "我能看懂这个产品适合谁、有什么用", "credible": "这些说法让我觉得可信", "interest": "我愿意进一步了解这个产品"}
SOURCES = ('ordinary_ai', 'system')


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def validate_case(case):
    for key in ('product', 'audience', 'goal', 'facts', 'sources', 'constraints'):
        if not case.get(key):
            raise ValueError('案例缺少 ' + key)
    if not isinstance(case['sources'], list) or any(not isinstance(s, dict) or not s.get('title') or not s.get('url', '').startswith('https://') for s in case['sources']):
        raise ValueError('来源需要标题和 https URL')


def page(pid, drafts, case):
    sections = []
    for label, text in drafts.items():
        fields = ''.join('<label>' + desc + '<select name="' + label + '_' + key + '" required><option value="">请选择</option>' + ''.join('<option>' + str(n) + '</option>' for n in range(1, 6)) + '</select></label>' for key, desc in DIMENSIONS.items())
        sections.append('<section><h2>稿件 ' + label + '</h2><pre>' + html.escape(text) + '</pre>' + fields + '<label>你记住的主要卖点是什么？<textarea name="' + label + '_message" required></textarea></label><label>哪里可信或不可信？还有什么疑问？<textarea name="' + label + '_reason" required></textarea></label></section>')
    config = json.dumps({'participant': pid, 'draft_hashes': {k: digest(v) for k, v in drafts.items()}}, ensure_ascii=False).replace('<', '\\u003c')
    return '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>推广内容试读</title><style>body{max-width:780px;margin:24px auto;padding:16px;font:17px/1.7 sans-serif;color:#21382e}section{border:1px solid #ccc;padding:20px;margin:20px 0}pre{white-space:pre-wrap;font:inherit}label{display:block;margin:18px 0}textarea{display:block;width:95%;min-height:75px;font:inherit}select,button{font:inherit;padding:8px}@media print{button{display:none}section{break-before:page}}</style><h1>两份推广内容，哪份更容易理解？</h1><p>编号：''' + html.escape(pid) + '''。请独立阅读，不讨论，不猜稿件来源。没有标准答案，不用填写姓名、电话或账号。你可以随时退出。</p><p>产品：''' + html.escape(case['product']) + '；面向：' + html.escape(case['audience']) + '''。</p><p>评分：1 很不同意，2 不同意，3 一般，4 同意，5 很同意。评价内容，不评价排版。这是试读，不是真实购买测试。</p><form>''' + ''.join(sections) + '''<label>你更愿意进一步了解哪份？<select name="preference" required><option value="">请选择</option><option>A</option><option>B</option><option value="tie">差不多</option><option value="neither">两份都不想</option></select></label><label>为什么？<textarea name="preference_reason" required></textarea></label><button>下载我的匿名回答</button><p id="saved"></p></form><script>const config=''' + config + ''';document.querySelector('form').onsubmit=e=>{e.preventDefault();const answers=Object.fromEntries(new FormData(e.target));const payload={...config,answers,submitted_at:new Date().toISOString()};const url=URL.createObjectURL(new Blob([JSON.stringify(payload,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=config.participant+'-回答.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);document.getElementById('saved').textContent='请把下载的回答文件交给主持人。没有自动上传任何数据。';};</script></html>'''


def generate(case, ordinary, system, output, count=5, seed=None, production=None):
    validate_case(case)
    if not ordinary.strip() or not system.strip() or ordinary.strip() == system.strip():
        raise ValueError('需要两份不同的非空稿件')
    if not 1 <= count <= 100:
        raise ValueError('人数需要 1 至 100')
    production = production or {s: {'elapsed_seconds': None, 'manual_edit_count': None, 'edited_characters': None} for s in SOURCES}
    for source in SOURCES:
        if source not in production:
            raise ValueError('制作记录需要普通 AI 和系统两份')
        for field in ('elapsed_seconds', 'manual_edit_count', 'edited_characters'):
            value = production[source].get(field)
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0):
                raise ValueError('制作记录只能填非负数或 null')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError('输出目录必须为空，避免覆盖旧评测')
    seed = secrets.randbits(128) if seed is None else seed
    rng = random.Random(seed)
    orders = [bool(i % 2) for i in range(count)]
    rng.shuffle(orders)
    mapping = {'schema_version': 1, 'seed': seed, 'case': case, 'production': production, 'participants': {}, 'limitations': '仅描述这批读者的理解、可信感和了解意愿，不证明咨询、成交或流量提升。'}
    texts = dict(zip(SOURCES, (ordinary, system)))
    for i, flip in enumerate(orders, 1):
        pid = 'P' + str(i).zfill(2)
        labels = {'A': 'system' if flip else 'ordinary_ai', 'B': 'ordinary_ai' if flip else 'system'}
        drafts = {k: texts[v] for k, v in labels.items()}
        mapping['participants'][pid] = {'labels': labels, 'draft_hashes': {k: digest(v) for k, v in drafts.items()}}
        (output / (pid + '-试读.html')).write_text(page(pid, drafts, case), encoding='utf-8')
    (output / '主持人专用-不要发给试读者.json').write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding='utf-8')
    return mapping



def normalize_response_identity(mapping, response, target_participant, confirmation):
    """Copy an explicitly confirmed questionnaire mix-up without changing answers.

    Returns (normalized_response, audit). The caller preserves the original file
    and audit; this helper does not infer identity from a filename or timestamps.
    """
    participants = mapping['participants']
    original_participant = response.get('participant')
    if (not isinstance(original_participant, str)
            or original_participant not in participants
            or not isinstance(target_participant, str)
            or target_participant not in participants):
        raise ValueError('未知试读编号')
    if original_participant == target_participant:
        raise ValueError('原编号与目标编号必须不同')
    if not isinstance(confirmation, str) or not confirmation.strip():
        raise ValueError('需要明确的身份更正确认理由')
    if response.get('draft_hashes') != participants[target_participant]['draft_hashes']:
        raise ValueError('目标问卷稿件版本或顺序不一致')
    normalized = deepcopy(response)
    normalized['participant'] = target_participant
    audit = {
        'original_participant': original_participant,
        'target_participant': target_participant,
        'confirmation': confirmation,
    }
    return normalized, audit


def summarize(mapping, responses):
    results, seen = [], set()
    for response in responses:
        pid = response.get('participant')
        if pid in seen or pid not in mapping['participants']:
            raise ValueError('未知或重复试读编号')
        seen.add(pid)
        info = mapping['participants'][pid]
        if response.get('draft_hashes') != info['draft_hashes']:
            raise ValueError('稿件版本不一致')
        answers = response.get('answers', {})
        row = {'participant': pid, 'scores': {}, 'reasons': {}}
        for label, source in info['labels'].items():
            scores = {}
            for key in DIMENSIONS:
                value = str(answers.get(label + '_' + key, ''))
                if value not in ('1', '2', '3', '4', '5'):
                    raise ValueError('评分缺失或越界')
                scores[key] = int(value)
            row['scores'][source] = scores
            row['reasons'][source] = {key: answers.get(label + '_' + key, '') for key in ('message', 'reason')}
            if any(not isinstance(v, str) or not v.strip() for v in row['reasons'][source].values()):
                raise ValueError('试读理由不能为空')
        choice = answers.get('preference')
        if choice not in ('A', 'B', 'tie', 'neither') or not isinstance(answers.get('preference_reason'), str) or not answers['preference_reason'].strip():
            raise ValueError('偏好及理由需要填写')
        row['preference'] = info['labels'].get(choice, choice)
        row['preference_reason'] = answers['preference_reason']
        results.append(row)
    scores = {source: {key: [row['scores'][source][key] for row in results] for key in DIMENSIONS} for source in SOURCES}
    return {'sample_size': len(results), 'results': results, 'scores': scores, 'production': mapping['production'], 'limitations': mapping['limitations'], 'missing_participants': sorted(set(mapping['participants']) - seen)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    build = commands.add_parser('generate')
    for key in ('case', 'ordinary', 'system', 'output'):
        build.add_argument('--' + key, required=True)
    build.add_argument('--count', type=int, default=5)
    build.add_argument('--production')
    review = commands.add_parser('summarize')
    review.add_argument('--mapping', required=True)
    review.add_argument('--responses', nargs='+', required=True)
    review.add_argument('--output', required=True)
    args = parser.parse_args()
    def read_json(path):
        return json.loads(Path(path).read_text(encoding='utf-8'))
    if args.command == 'generate':
        generate(read_json(args.case), Path(args.ordinary).read_text(encoding='utf-8'), Path(args.system).read_text(encoding='utf-8'), args.output, args.count, production=read_json(args.production) if args.production else None)
    else:
        data = summarize(read_json(args.mapping), [read_json(p) for p in args.responses])
        out = Path(args.output)
        if out.exists():
            raise ValueError('不覆盖已有报告，请用新输出路径')
        out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
