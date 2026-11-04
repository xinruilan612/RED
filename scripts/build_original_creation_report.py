#!/usr/bin/env python3
"""Build shareable, redacted acceptance reports from local frozen evidence only."""
import argparse
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = {'owner', 'owner_id', 'account_id', 'connection_id', 'api_key', 'password', 'cookie', 'csrf'}


def sanitize(value):
    if isinstance(value, dict):
        return {k: '[已隐去，按所属账号隔离]' if k in PRIVATE else sanitize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize(v) for v in value]
    return value


def matched_review(snapshot, draft):
    candidates = [snapshot.get('prior_review'), *snapshot.get('reviews', []), snapshot.get('review')]
    return next((r for r in reversed(candidates) if isinstance(r, dict) and
                 r.get('draft_ref') == draft.get('ref') and
                 r.get('snapshot_id') == draft.get('snapshot_id')), None)


def build(source, destination):
    data = json.loads(source.read_text())
    blocks = []
    def add(kind, value):
        blocks.append((kind, sanitize(value)))
    add('h1', '原创文案能力：六场景真实流程验收')
    add('p', data['boundary'] + '。本报告保留最终完整稿件与实际证据，不将模型审核通过等同于完全符合质量要求。')
    attempts = data['cases'] + data.get('previous_attempts', [])
    calls = {c['id']: c for item in attempts for c in item.get('calls', [])}
    unknown = [c for c in calls.values() if c.get('tokens') is None]
    add('p', f"授权上限 US${data['budget_authorized_usd']:.2f}；保守计费账本 US${data['conservative_cost_usd']:.6f}；去重调用 {len(calls)} 次，其中用量未知 {len(unknown)} 次。未知调用按预留 token × 账本费率计入，不作零费用处理；这不是服务商最终账单。")
    add('p', '六个最终场景均须逐项查看下方状态；WAITING_USER / final_confirmation 表示等待用户确认，未发布。各轮修复保留历史失败与旧稿，不能将早期尝试合并为一次无失败运行。')
    add('p', '验收期间运行提示词由 retrieval1 迭代到 retrieval2、retrieval3；后续又压缩重复阶段输入以满足剩余预算。每个案例列出实际调用的 prompt_version，早期成稿没有假装在最终提示词版本下重新生成。')
    add('h2', '人工核对仍发现的质量问题')
    add('p', '美妆图文 CTA 使用“便携包装”，现有规格只有透明方管、斜面刷头和净含量，不能据此证明便携性；应改为“包装细节”。口播稿存在正文与 CTA 重复提问以及“本次提供的规格”等范围说明，可进一步清理。以下保留原始成稿，不静默改写验收产物。')
    add('p', '样例对照与逐字引文匹配只能证明有限资料范围内的引用关系，不能证明资料真实、全网原创或发布效果。模型审核中的 originality_risk=unknown 按未知保留，不升级为原创性通过。')
    audit_notes = {
        '美妆图文': '规格引用相符，未继承21天试用或不沾杯承诺；CTA中的“便携包装”缺少依据，应改为“包装细节”。',
        '摄影图文': '重量、收纳长度、展开高度与便携袋事实相符，未继承八级风稳定性或保证装包结论；正文与CTA重复，原文“包和称重量一下”表达生硬，需编辑。',
        '美妆换口播': '事实相符，未照搬样例独特表述；“这条只讲这些能被核对的规格”仍偏内部范围说明，正文与CTA重复，应清理。',
        '数码图文': '事实相符，先前关于USB的错误主张在最终稿中删除；结尾总结存在重复，仍有精简空间。',
        '家具图文': '材质与尺寸事实相符，未继承五年使用经历；尺寸说明与结构重复，应精简。',
        '园艺缺样例': '缺少同领域样例时只使用通用方法和本次事实；托盘说明重复，外部尺寸不等于实际适配证明，应保留测量核对边界。',
    }
    for index, case in enumerate(data['cases'], 1):
        path = source.parent / (case['run_id'] + '.json')
        snapshot = json.loads(path.read_text()) if path.exists() else case
        drafts = snapshot.get('drafts', case.get('drafts', []))
        draft = drafts[-1] if drafts else {}
        review = matched_review(snapshot, draft) if draft else None
        retrieval = case.get('retrieval', {})
        add('h2', f"{index}. {case['name']}")
        add('p', f"验收记录状态：{case.get('status')} / {case.get('wait_reason')}。" + (f"后续关闭标记：{case.get('closure_note')}" if case.get('closure_note') else ''))
        add('h3', '分类与真实检索条件')
        add('json', {'classification': case.get('classification'), 'engine': retrieval.get('engine'),
                     'reranker': retrieval.get('reranker'), 'filters': retrieval.get('filters'),
                     'gaps': retrieval.get('gaps', []), 'example_gap': not bool(retrieval.get('groups', {}).get('examples')),
                     'prompt_versions': sorted({c.get('prompt_version', 'unknown') for c in case.get('calls', [])}),
                     'draft_ref': draft.get('ref'), 'snapshot_id': draft.get('snapshot_id')})
        for key, label in [('methods', '通用创作方法'), ('examples', '领域参考样例'), ('facts', '独立事实依据')]:
            group = retrieval.get('groups', {}).get(key, [])
            add('h3', f'{label}（{len(group)} 条）')
            if not group:
                add('p', '没有匹配材料；未用其他领域样例补位。')
            for record in group:
                add('json', {k: record.get(k) for k in ['title', 'source_id', 'version', 'page', 'offset', 'classification', 'score', 'semantic_score', 'topic_coverage']})
                add('quote', record.get('text', '正文未留存'))
        add('h3', '最后版本完整成稿（未发布）')
        content = draft.get('content', {})
        add('h4', content.get('selected_title', '尚无成稿'))
        add('quote', content.get('body', ''))
        add('p', '行动引导：' + content.get('cta', ''))
        add('p', '标签：' + ' / '.join(content.get('tags', [])))
        add('h3', '独立人工抽查意见')
        add('p', audit_notes.get(case['name'], '本场景尚无单独人工意见。'))
        add('p', '本次对照未发现继承样例中的21天、不沾杯、八级风、180天、五年等私有经历或测试结论；此结论仅覆盖本报告列出的受控样例。')
        add('h3', '仅匹配当前稿件与快照的审核')
        if review:
            add('json', {k: review.get(k) for k in ['decision', 'next_action', 'draft_ref', 'snapshot_id', 'checks', 'issues', 'claim_map', 'reference_records', 'limitations']})
        else:
            add('p', '未找到同时匹配当前 draft_ref 与 snapshot_id 的审核；不得使用旧稿审核替代。')
    add('h2', '历史失败、被替代尝试与费用未知记录')
    for item in data.get('previous_attempts', []):
        add('h3', item['name'])
        add('json', {k: item.get(k) for k in ['status', 'wait_reason', 'background', 'closed_for_next_case', 'closure_note']})
        add('json', [{k: c.get(k) for k in ['stage', 'status', 'error', 'tokens', 'reserved_tokens', 'rate', 'prompt_version']} for c in item.get('calls', [])])
    add('p', '上述历史状态为当时保存的记录，RUNNING 不表示报告生成时仍在执行；以最终六场景验收和后续关闭标记为准。失败调用没有自动按成功计入，未知费用保守预留。')
    add('h2', '网页证据与核验边界')
    add('p', '网页任务沿用 /api/runs → PostgreSQL 后台队列 → Worker → 四角色 → 审核 → 人工确认；分组检索资料与事实对应记录通过同一网页稿件依据入口查看。附图 web-retrieval.jpg 为本轮网页截图。')
    add('p', '自动化检查在阶段交付中独立记录：全量 813 项、前端 131 项及最后定向 66 项通过；它们与真实模型六场景、人工质量核对是三类证据。报告生成不执行模型、不进行外部联网、不自动给出“全部质量通过”。')
    md, body = [], []
    for kind, value in blocks:
        text = json.dumps(value, ensure_ascii=False, indent=2) if kind == 'json' else str(value)
        escaped = html.escape(text)
        if kind.startswith('h'):
            md.append('#' * int(kind[1:]) + ' ' + text)
            body.append(f'<{kind}>{escaped}</{kind}>')
        elif kind == 'json':
            md.append('```json\n' + text + '\n```')
            body.append('<details><summary>展开结构化记录</summary><pre>' + escaped + '</pre></details>')
        elif kind == 'quote':
            md.append('\n'.join(('> ' + line if line else '>') for line in text.splitlines()))
            body.append('<blockquote>' + escaped + '</blockquote>')
        else:
            md.append(text)
            body.append('<p>' + escaped + '</p>')
    destination.mkdir(parents=True, exist_ok=True)
    (destination / 'REPORT.md').write_text('\n\n'.join(md) + '\n')
    stylesheet = 'body{font:16px/1.75 system-ui,sans-serif;max-width:1000px;margin:40px auto;padding:0 24px;color:#21332d;background:#f7f9f6}h1,h2{color:#173e30}h2{border-top:2px solid #b8cfc4;padding-top:28px;margin-top:40px}blockquote{white-space:pre-wrap;background:white;border-left:4px solid #67a58b;margin:16px 0;padding:18px 22px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#edf1ed;padding:18px;font-size:13px}details{margin:12px 0}summary{cursor:pointer}img{max-width:100%}'
    (destination / 'report.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>原创文案六场景验收</title><style>' + stylesheet + '</style><main>' + '\n'.join(body) + '<img src="web-retrieval.jpg" alt="本轮网页分组检索证据截图"></main></html>')
    return len(data['cases']), len(calls)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, default=ROOT / 'runtime/original_creation_acceptance/report.json')
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/evidence/original-creation')
    args = parser.parse_args()
    count, calls = build(args.source, args.output)
    print(f'Generated {count} cases, {calls} distinct calls; private ownership fields redacted.')
