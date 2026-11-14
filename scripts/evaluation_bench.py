"""Three-arm comparison study for the multi-agent pipeline.

Arms:
  A  single-shot model call        (no retrieval, no roles)
  B  production multi-agent        (retrieval disabled)
  C  production multi-agent        (classified retrieval enabled)

Offline subcommands never call a model and never touch the network:

  --self-check              validate the gold set and prove metrics recompute
  --score RESULTS.json      recompute metrics for recorded drafts
  --report RESULTS.json     regenerate REPORT.md from recorded results

Live execution is expensive and therefore separate and explicit:

  --execute-authorized --budget-usd N --origin http://127.0.0.1:8890

Arm A uses the operator's default model connection directly. It is outside the
run ledger, so its usage is recorded in the results file and must be reconciled
by the operator. Do not raise --budget-usd beyond an authorization the operator
has actually granted.
"""
import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.evaluation import aggregate, draft_text, score_draft  # noqa: E402

GOLD = ROOT / 'docs/evidence/evaluation/gold_set.json'
OUT = ROOT / 'docs/evidence/evaluation'
ARMS = ('A', 'B', 'C')
REQUIRED_ITEM = {'id', 'topic', 'expected_points', 'forbidden_claims'}


def load_gold_set(path=GOLD):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def validate_gold_set(document):
    """Fail loudly on a malformed or ambiguous gold set; never silently skip an item."""
    items = document.get('items')
    if not isinstance(items, list) or not items:
        raise ValueError('gold set must contain a non-empty items list')
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError('each gold item must be an object')
        missing = REQUIRED_ITEM - set(item)
        if missing:
            raise ValueError('gold item %r missing %s' % (item.get('id'), sorted(missing)))
        if item['id'] in seen:
            raise ValueError('duplicate gold item id %r' % item['id'])
        seen.add(item['id'])
        if not isinstance(item['expected_points'], list) or not item['expected_points']:
            raise ValueError('gold item %r needs at least one expected point' % item['id'])
        for pattern in item['forbidden_claims']:
            try:
                re.compile(pattern)
            except re.error as error:
                raise ValueError('gold item %r has an invalid forbidden pattern: %s' % (item['id'], error)) from None
    return items


def item_by_id(items, item_id):
    for item in items:
        if item['id'] == item_id:
            return item
    raise KeyError(item_id)


def score_record(record, item):
    return score_draft(record.get('draft') or {}, record.get('references') or [], item)


def score_results(document, items=None):
    """Recompute every score from stored drafts; the stored score is never trusted.

    ``items`` lets a caller score against a non-default gold set (e.g. the real
    product set). Without it the document's recorded gold_set_path is used, then
    the default file, so a recorded run can always be re-scored offline.
    """
    if items is not None:
        items = validate_gold_set({'items': items})
    elif document.get('items'):
        items = validate_gold_set(document)
    elif document.get('gold_set_path'):
        items = validate_gold_set(load_gold_set(document['gold_set_path']))
    else:
        items = validate_gold_set(load_gold_set())
    scored = []
    for record in document.get('records') or []:
        item = item_by_id(items, record['item_id'])
        scored.append({**record, 'score': score_record(record, item)})
    document = {**document, 'records': scored, 'summary': aggregate(scored)}
    return document


def _pct(value):
    return '—' if value is None else '%.1f%%' % (value * 100)


def write_report(document, path):
    summary = document.get('summary') or {}
    lines = ['# 有迹三组对照实验报告', '',
             '生成时间：%s' % time.strftime('%Y-%m-%d %H:%M:%S'),
             '题库：`docs/evidence/evaluation/gold_set.json`（版本 %s）' % document.get('gold_set_hash', '未记录'),
             '评分标准：`docs/evidence/evaluation/rubric.md`（预注册，实验后未修改）', '',
             '## 一 结论摘要', '']
    if not summary:
        lines.append('尚无已判分记录。')
    else:
        lines += ['| 组 | 样本数 | 事实支撑率 | 要点覆盖率 | 禁用断言率 | 平均正文字数 |',
                  '| --- | ---: | ---: | ---: | ---: | ---: |']
        labels = {'A': 'A 单次直写', 'B': 'B 多Agent无检索', 'C': 'C 多Agent+分类检索'}
        for arm in sorted(summary):
            row = summary[arm]
            lines.append('| %s | %d | %s | %s | %s | %s |' % (
                labels.get(arm, arm), row['n'], _pct(row['fact_support_rate']),
                _pct(row['expected_point_coverage']), _pct(row['forbidden_hit_rate']),
                '—' if row['mean_body_chars'] is None else '%.0f' % row['mean_body_chars']))
    lines += ['', '## 二 逐条记录', '',
              '| 组 | 题目 | 状态 | 事实支撑 | 要点覆盖 | 禁用断言 | 检索方式 | 正文字数 |',
              '| --- | --- | --- | ---: | ---: | ---: | --- | ---: |']
    for record in document.get('records') or []:
        score = record.get('score') or {}
        forbidden = score.get('forbidden') or {}
        lines.append('| %s | %s | %s | %s | %s | %s | %s | %s |' % (
            record.get('arm'), record.get('item_id'), record.get('status', 'done'),
            _pct((score.get('fact_support') or {}).get('rate')),
            _pct((score.get('coverage') or {}).get('rate')),
            '命中：' + '；'.join(hit['match'] for hit in forbidden.get('hits') or []) if forbidden.get('any_hit') else '无',
            record.get('retrieval_mode') or '—', score.get('chars', '—')))
    failures = [r for r in document.get('records') or [] if r.get('status') not in (None, 'done')]
    lines += ['', '## 三 失败与缺失样本', '']
    if failures:
        lines += ['| 组 | 题目 | 状态 | 说明 |', '| --- | --- | --- | --- |']
        for record in failures:
            lines.append('| %s | %s | %s | %s |' % (record.get('arm'), record.get('item_id'),
                                                    record.get('status'), record.get('detail', '')))
    else:
        lines.append('本文件没有记录失败样本。**若实验中确实出现过失败，此处为空即为报告缺陷。**')
    lines += ['', '## 四 边界与限制', '',
              '- 事实支撑率是词汇层面的依据检测，**不是事实核查通过**，也不证明来源权威。',
              '- 要点覆盖率使用中文 bigram 词项重叠，同义改写可能被误判为未覆盖，只用于组间比较。',
              '- 标题中的计数词会被计入可核查句，属于保守偏差。',
              '- 样本量小于 8 题时只能表述为初步观察，不得表述为统计结论。',
              '- 模型判分（judge）与人工抽检结果另附；分歧以自动判分为准并记录。',
              '- 不得将本报告结论表述为爆款概率或流量提升。']
    if document.get('notes'):
        lines += ['', '## 五 本次运行的补充说明', ''] + ['- %s' % n for n in document['notes']]
    Path(path).write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return path


def gold_set_hash(document):
    payload = json.dumps(document.get('items'), ensure_ascii=False, sort_keys=True).encode('utf-8')
    return hashlib.sha256(payload).hexdigest()


def self_check(gold_path=GOLD):
    """Prove the offline layer works end to end without any model call."""
    document = load_gold_set(gold_path)
    items = validate_gold_set(document)
    results = {'schema': 'youji-evaluation-results/1', 'gold_set_hash': gold_set_hash(document),
               'records': [], 'notes': ['self-check：未调用模型，未产生费用']}
    for item in items:
        for arm in ARMS:
            results['records'].append({'arm': arm, 'item_id': item['id'], 'status': 'skipped',
                                       'detail': 'self-check 不生成稿件', 'draft': {},
                                       'references': [item['facts']] if item.get('facts') else []})
    results = score_results(results, items)
    for record in results['records']:
        score = record['score']
        assert score['fact_support']['rate'] is None, 'empty draft must report a null rate'
        assert score['forbidden']['any_hit'] is False, 'empty draft cannot hit a forbidden claim'
    return {'items': len(items), 'arms': len(ARMS),
            'records': len(results['records']),
            'forbidden_patterns': sum(len(i['forbidden_claims']) for i in items),
            'expected_points': sum(len(i['expected_points']) for i in items),
            'gold_set_hash': results['gold_set_hash'],
            'summary': results['summary']}


SINGLE_SHOT_SYSTEM = (
    '你是小红书图文作者。依据给定材料写一篇可直接发布的笔记。'
    '只输出一个 JSON 对象，字段为 selected_title（字符串）、body（字符串）、'
    'cta（字符串）、tags（字符串数组）。'
    '不得声称亲测，不得写入材料未提供的规格、价格、功效或个人经历。'
)


def single_shot(store, owner, item, gold):
    """Arm A: one model call given everything the other arms could retrieve.

    This is deliberately generous to the baseline: it receives the same method,
    facts and sample text that arms B and C have to retrieve. If C still scores
    better on citation discipline, the difference comes from the pipeline rather
    than from withholding information.
    """
    from backend.model_connections import ModelConnections
    from backend.provider import load_config
    connections = ModelConnections(store, load_config())
    route = connections.route(owner)
    if route is None:
        raise RuntimeError('no default model connection configured')
    parts = []
    if gold.get('shared_method'):
        parts.append('【通用方法】\n' + gold['shared_method'])
    if item.get('facts'):
        parts.append('【本次产品资料】\n' + item['facts'])
    if item.get('sample'):
        parts.append('【写法样例（只学结构，不继承其经历与结论）】\n' + item['sample'])
    brief = {'topic': item['topic'], 'domain': item.get('domain'), 'format': item.get('format'),
             'word_count': 200, 'requirement': '写成可阅读成稿'}
    messages = [{'role': 'system', 'content': SINGLE_SHOT_SYSTEM},
                {'role': 'user', 'content': '\n\n'.join(parts + [json.dumps(brief, ensure_ascii=False)])}]
    value, tokens, meta = connections.adapter(route, owner).complete_result(messages, max_tokens=3000)
    return value, tokens, meta, route


def live(args):
    if not args.execute_authorized:
        raise SystemExit('explicit --execute-authorized is required for paid execution')
    if not args.budget_usd or args.budget_usd <= 0:
        raise SystemExit('--budget-usd must be a positive authorization the operator has granted')
    import requests
    from backend.api import settings
    from backend.auth import Auth
    from backend.store import Store
    from backend.knowledge import Knowledge
    from backend.accounts import PROFILE_FIELDS

    gold = load_gold_set(args.gold_set)
    items = validate_gold_set(gold)
    if args.limit:
        items = items[:args.limit]
    store = Store(settings()['DATABASE_URL'])
    with store.connect() as db:
        row = db.execute('SELECT id,owner FROM users LIMIT 1').fetchone()
    if not row:
        raise SystemExit('no website account found')
    auth = Auth(store)
    token = auth.issue(row[0])
    session = requests.Session()
    session.trust_env = False
    session.cookies.set('youji_session', token)
    session.headers.update({'Origin': args.origin, 'X-CSRF-Token': auth.session(token)['csrf']})

    def get(path):
        response = session.get(args.origin + path, timeout=120)
        response.raise_for_status()
        return response.json()

    def post(path, data):
        response = session.post(args.origin + path, json=data, timeout=180)
        if response.status_code >= 400:
            raise RuntimeError('%s %s' % (response.status_code, response.text[:400]))
        return response.json()

    state = get('/api/operations')
    name = '对照实验 · 独立账号'
    account = next((a for a in state['accounts'] if a['name'] == name), None)
    if account is None:
        state = post('/api/operations', {'action': 'save_account', 'version': state['version'], 'key': str(uuid4()),
                                         'payload': {'id': None, 'name': name, 'platform': 'xiaohongshu',
                                                     'profile': {**{k: '' for k in PROFILE_FIELDS}, 'weekly_frequency': 3}}})
        account = next(a for a in state['accounts'] if a['name'] == name)
    account_id = account['id']

    def active(run):
        # A blocked run still holds the single active-task slot, so it must be
        # released too; otherwise the next item fails with RUN_ALREADY_ACTIVE.
        return (run.get('run_status') in ('RUNNING', 'WAITING_USER')
                or (run.get('background') or {}).get('status') in ('queued', 'running', 'pausing', 'blocked'))

    def release_slot():
        """Cancel only THIS experiment account's active runs to free the single slot.

        Runs belonging to the operator's own accounts are never touched.
        """
        freed = []
        for existing in get('/api/runs'):
            context = existing.get('context') or {}
            if ((context.get('operations') or {}).get('account_id')) != account_id:
                continue
            if not active(existing):
                continue
            post('/api/runs/' + existing['run_id'] + '/actions',
                 {'action': 'cancel', 'version': existing['status_version'], 'key': str(uuid4()), 'payload': {}})
            freed.append(existing['run_id'])
        return freed

    stale = release_slot()
    if stale:
        print(json.dumps({'released_stale_runs': stale}, ensure_ascii=False), flush=True)
    kb = Knowledge(store)
    existing = {d['title']: d for d in get('/api/knowledge?account_id=' + account_id)}

    def seed(title, text, label):
        if title in existing:
            return existing[title]['id']
        doc = post('/api/knowledge', {'account_id': account_id, 'title': title, 'text': text, 'classification': label})
        existing[title] = doc
        return doc['id']

    seed('对照实验通用原创方法', gold['shared_method'],
         {'domains': ['general'], 'channel': 'any', 'format': 'any', 'material_type': 'method'})
    material_ids = {}
    for item in items:
        if item.get('facts'):
            material_ids[item['id']] = seed('对照实验事实 · ' + item['id'], item['facts'],
                                            {'domains': [item.get('domain', 'general')], 'channel': 'any',
                                             'format': 'any', 'material_type': 'fact'})
        if item.get('sample'):
            seed('对照实验样例 · ' + item['id'], item['sample'],
                 {'domains': [item.get('domain', 'general')], 'channel': 'xiaohongshu',
                  'format': item.get('format', 'note'), 'material_type': 'example'})

    results = {'schema': 'youji-evaluation-results/1', 'gold_set_hash': gold_set_hash(gold),
               'origin': args.origin, 'budget_authorized_usd': args.budget_usd,
               'account_id': account_id, 'records': [],
               'gold_set_path': str(Path(args.gold_set)),
               'notes': ['真实模型调用；A 组为单次直写，直接在默认模型连接上执行、'
                         '不经运行账本，其费用按 token 估算并记入 arm_a_spent_usd']}
    results_path = OUT / ('results-%s.json' % time.strftime('%Y%m%d-%H%M%S'))
    OUT.mkdir(parents=True, exist_ok=True)

    def save():
        results_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')

    save()
    spent = 0.0
    arm_a_spent = 0.0
    # Arm A: one call per item, outside the run ledger; cost derived from tokens.
    if 'A' in args.arms:
        for item in items:
            if arm_a_spent >= args.budget_usd:
                results['records'].append({'arm': 'A', 'item_id': item['id'], 'status': 'skipped',
                                           'detail': '预算上限已达，未发出请求'})
                save()
                continue
            record = {'arm': 'A', 'item_id': item['id'], 'status': 'created', 'retrieval_mode': 'none'}
            for attempt in range(args.retries + 1):
                record['attempts'] = attempt + 1
                try:
                    value, tokens, meta, route = single_shot(store, row[1], item, gold)
                    cost = float(tokens or 0) * float(getattr(route, 'rate', 0) or 0)
                    arm_a_spent += cost
                    record.update({'status': 'done', 'draft': value if isinstance(value, dict) else {},
                                   'calls': 1,
                                   # Score arm A against the SAME material it was given,
                                   # otherwise its fact-support rate is trivially zero and
                                   # the comparison would be rigged against the baseline.
                                   'references': [item['facts']] if item.get('facts') else [],
                                   'arm_a_tokens': tokens,
                                   'cost_usd': round(cost, 6), 'arm_a_request_id': (meta or {}).get('request_id')})
                    break
                except Exception as error:  # recorded, never silently dropped
                    record.update({'status': 'failed', 'detail': str(error)[:400]})
                    if attempt < args.retries:
                        time.sleep(2)
            results['records'].append(record)
            results['arm_a_spent_usd'] = round(arm_a_spent, 6)
            results['cost_estimate_usd'] = round(arm_a_spent, 6)
            save()
            print(json.dumps({'arm': 'A', 'item': item['id'], 'status': record['status'],
                              'spent_usd': round(arm_a_spent, 6)}, ensure_ascii=False), flush=True)
    def background_material(item):
        """Same material set arm A receives, offered to B as task background."""
        parts = []
        if gold.get('shared_method'):
            parts.append('【通用方法】\n' + gold['shared_method'])
        if item.get('facts'):
            parts.append('【本次产品资料】\n' + item['facts'])
        if item.get('sample'):
            parts.append('【写法样例（只学结构，不继承其经历与结论）】\n' + item['sample'])
        return '\n\n'.join(parts)

    for arm in [a for a in ('B', 'C') if a in args.arms]:
        for item in items:
            if spent + arm_a_spent >= args.budget_usd:
                results['records'].append({'arm': arm, 'item_id': item['id'], 'status': 'skipped',
                                           'detail': '预算上限已达，未发出请求'})
                save()
                continue
            record = {'arm': arm, 'item_id': item['id'], 'status': 'created', 'attempts': 0}

            def once():
                run = post('/api/runs', {
                    'mode': 'live', 'topic': item['topic'], 'audience': '需要核对规格的普通读者',
                    'tone': '清楚、自然、克制',
                    # B must actually receive the material; otherwise it is not a
                    # "no retrieval" baseline but a "no information" baseline.
                    # C relies on the classified retrieval instead.
                    'material': (background_material(item) +
                                 '\n\n请依据以上资料写成可阅读成稿，不得声称亲测。') if arm == 'B'
                                else '请依据资料库中检索到的资料写成可阅读成稿，不得声称亲测。',
                    'allow_hypothesis': True,
                    'operations': {'account_id': account_id, 'platform': 'xiaohongshu', 'account': name},
                    'creation': {'domains': [item.get('domain', 'general')], 'channel': 'xiaohongshu',
                                 'format': item.get('format', 'note'), 'goal': '清楚介绍已有规格', 'word_count': 200},
                    'knowledge': {'enabled': arm == 'C', 'automatic_references': arm == 'C',
                                  'document_ids': [material_ids[item['id']]] if material_ids.get(item['id']) else []},
                    # Arm C really searches the web and reads official pages;
                    # B stays offline so the two effects remain separable.
                    'web_research': ({'enabled': True, 'queries': (item.get('search_queries') or [item['topic']])[:2],
                                      'provider': 'baidu', 'targets': ['web']}
                                     if arm == 'C' else {'enabled': False, 'queries': []}),
                })
                run_id = run['run_id']
                record['run_id'] = run_id
                post('/api/runs/' + run_id + '/background',
                     {'action': 'start', 'version': run['status_version'], 'key': str(uuid4())})
                deadline = time.monotonic() + args.timeout
                in_flight = ('RUNNING', 'PENDING', 'NEW', 'QUEUED')
                while time.monotonic() < deadline:
                    run = get('/api/runs/' + run_id)
                    state = run.get('run_status')
                    bg = (run.get('background') or {}).get('status')
                    # Stop on an explicit terminal background state, or when the
                    # business run is no longer in flight. Watching background alone
                    # ended the poll early while the run was still RUNNING.
                    if bg in ('blocked', 'failed'):
                        break
                    if state not in in_flight and bg not in ('queued', 'running', 'pausing'):
                        break
                    time.sleep(3)
                drafts = run.get('drafts') or []
                context = run.get('context') or {}
                raw_status = run.get('run_status') or 'unknown'
                # WAITING_USER/SUCCEEDED are terminal success states for scoring:
                # the study never accepts the draft on the user's behalf.
                record.update({'status': 'done' if raw_status in ('WAITING_USER', 'SUCCEEDED') else raw_status,
                               'run_status': raw_status,
                               'draft': (drafts[-1]['content'] if drafts else {}),
                               'retrieval_mode': (context.get('creation_retrieval') or {}).get('engine'),
                               'calls': len(run.get('calls') or []),
                               'references': ([m.get('text', '') for m in
                                              (context.get('creation_retrieval') or {}).get('sources') or []]
                                              if arm == 'C'
                                              else ([item['facts']] if item.get('facts') else []))})
                if not drafts:
                    record['status'] = 'no_draft'
                # The product allows one active task at a time. Release it without
                # accepting anything: the draft is already captured above.
                if active(run):
                    release_slot()
                    record['slot_released'] = True

            # Transient upstream failures (proxy tunnel never established, model
            # contract violation) leave no draft and cost nothing when the request
            # was never sent. Retry those; a produced draft is never retried.
            for attempt in range(args.retries + 1):
                record['attempts'] = attempt + 1
                try:
                    once()
                except Exception as error:  # recorded, never aborting the whole study
                    record.update({'status': 'failed', 'detail': str(error)[:400]})
                if record.get('status') == 'done' and record.get('draft'):
                    break
                if attempt < args.retries:
                    record['last_retry_status'] = record.get('status')
                    release_slot()
                    time.sleep(2)
            results['records'].append(record)
            save()
            with store.connect() as db:
                # Scope the ledger sum to THIS study. The unscoped query counted the
                # operator's entire call history and consumed the budget instantly.
                ids = [r['run_id'] for r in results['records'] if r.get('run_id')]
                if ids:
                    marks = ','.join('?' for _ in ids)
                    spent = float(db.execute(
                        'SELECT COALESCE(SUM(COALESCE(c.actual,c.reserved)*a.rate),0) FROM live_calls c '
                        'JOIN model_audit a ON a.call_id=c.id WHERE c.run_id IN (' + marks + ')',
                        ids).fetchone()[0] or 0)
                else:
                    spent = 0.0
            results['cost_estimate_usd'] = round(spent + arm_a_spent, 6)
            save()
            print(json.dumps({'arm': arm, 'item': item['id'], 'status': record['status'],
                              'spent_usd': round(spent, 6)}, ensure_ascii=False), flush=True)
    results = score_results(results, items)
    save()
    report = write_report(results, OUT / ('REPORT-%s.md' % time.strftime('%Y%m%d-%H%M%S')))
    auth.logout(token)
    print(json.dumps({'results': str(results_path), 'report': str(report),
                      'cost_estimate_usd': results.get('cost_estimate_usd')}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--gold-set', default=str(GOLD))
    parser.add_argument('--self-check', action='store_true')
    parser.add_argument('--score', metavar='RESULTS.json')
    parser.add_argument('--report', metavar='RESULTS.json')
    parser.add_argument('--execute-authorized', action='store_true')
    parser.add_argument('--budget-usd', type=float, default=0.0)
    parser.add_argument('--origin', default='http://127.0.0.1:8890')
    parser.add_argument('--limit', type=int, default=0)
    parser.add_argument('--timeout', type=int, default=600)
    parser.add_argument('--arms', default='A,B,C',
                        help='comma separated subset of A,B,C (arm A bypasses the run ledger)')
    parser.add_argument('--retries', type=int, default=2,
                        help='retries for a no-draft run caused by a transient upstream failure')
    args = parser.parse_args()
    args.arms = tuple(part.strip().upper() for part in str(args.arms).split(',') if part.strip())
    unknown = [arm for arm in args.arms if arm not in ARMS]
    if unknown:
        parser.error('unknown arm(s): %s' % ','.join(unknown))
    if args.self_check:
        print(json.dumps(self_check(args.gold_set), ensure_ascii=False, indent=2))
        return
    if args.score:
        document = score_results(json.loads(Path(args.score).read_text(encoding='utf-8')))
        target = Path(args.score).with_suffix('.scored.json')
        target.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'scored': str(target), 'summary': document['summary']}, ensure_ascii=False, indent=2))
        return
    if args.report:
        document = json.loads(Path(args.report).read_text(encoding='utf-8'))
        document = score_results(document) if document.get('records') else document
        target = OUT / 'REPORT.md'
        write_report(document, target)
        print(json.dumps({'report': str(target)}, ensure_ascii=False))
        return
    if args.execute_authorized:
        live(args)
        return
    parser.error('choose --self-check, --score, --report or --execute-authorized')


if __name__ == '__main__':
    main()
