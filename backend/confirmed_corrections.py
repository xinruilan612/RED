"""Internal exact-paragraph correction after explicit user authorization.

No public endpoint or model tool. Previous drafts and acceptance events remain
immutable; the resulting version is manually accepted, never AI-approved.
"""
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
import json
import re
from uuid import uuid4

from backend.contracts import integer, require
from backend.media_exports import confirmed_snapshot
from backend.workflow import Run, digest


def remove_confirmed_paragraph(store, owner, run_id, expected_version, expected_ref, paragraph, key):
    """Caller must have explicit user consent to remove this exact paragraph."""
    integer(expected_version, 'expected_version')
    require(isinstance(key, str) and key and isinstance(expected_ref, str) and expected_ref,
            'INVALID_INPUT', '必须提供幂等键和已确认版本')
    require(isinstance(paragraph, str) and paragraph.strip() == paragraph and paragraph
            and '\n' not in paragraph and '\r' not in paragraph,
            'INVALID_INPUT', '仅支持精确删除一个独立段落')
    fingerprint = digest({'action': 'remove_confirmed_paragraph', 'version': expected_version,
                          'ref': expected_ref, 'paragraph': paragraph})
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        run = store._get(db, run_id, owner)
        prior = db.execute('SELECT hash,response FROM commands WHERE run_id=? AND key=?', (run_id, key)).fetchone()
        if prior:
            require(prior[0] == fingerprint, 'IDEMPOTENCY_CONFLICT', '幂等键已用于其他操作')
            return Run(**json.loads(prior[1]))
        require(run.status_version == expected_version and run.accepted_ref == expected_ref,
                'VERSION_CONFLICT', '已确认版本已更新')
        confirmed_snapshot(run)
        require(run.drafts[-1]['ref'] == expected_ref, 'VERSION_CONFLICT', '存在较新的稿件，不能纠正旧确认版本')
        if db.has_table('runtime_jobs'):
            job = db.execute('SELECT status FROM runtime_jobs WHERE run_id=?', (run_id,)).fetchone()
            require(not job or job[0] not in ('queued', 'running', 'pausing'), 'JOB_ACTIVE', '后台任务尚未停稳')
        if db.has_table('live_steps'):
            require(not db.execute("SELECT 1 FROM live_steps WHERE run_id=? AND state='running'", (run_id,)).fetchone(),
                    'JOB_ACTIVE', '模型仍在执行')
        old = run.drafts[-1]
        content = deepcopy(old['content'])
        pieces = re.split(r'(\r?\n[ \t]*\r?\n(?:[ \t]*\r?\n)*)', content['body'])
        matches = [i for i in range(0, len(pieces), 2) if pieces[i] == paragraph]
        require(len(matches) == 1, 'INVALID_INPUT', '指定独立段落必须精确出现一次')
        index = matches[0]
        if index + 1 < len(pieces):
            del pieces[index:index + 2]
        elif index:
            del pieces[index - 1:index + 1]
        else:
            del pieces[index]
        content['body'] = ''.join(pieces)
        require(content['body'].strip(), 'INVALID_INPUT', '删除后正文不能为空')
        reason = '用户明确要求移除指定独立段落并设为当前确认稿；人工修正，未进行新的 AI 审核'
        old_acceptance = deepcopy(run.acceptance)
        item = {'ref': f'{uuid4()}@1', 'content': content, 'content_hash': digest(content),
                'snapshot_id': run.snapshot_id, 'actor': 'user',
                'correction': {'previous_ref': old['ref'], 'removed_paragraph': paragraph, 'reason': reason}}
        run.drafts.append(item)
        run.prior_review = deepcopy(run.review or run.prior_review)
        run.review = None
        run.accepted_ref = item['ref']
        run.acceptance = {'mode': 'manual_override', 'draft_ref': item['ref'], 'content_hash': item['content_hash'],
                          'snapshot_id': run.snapshot_id, 'review_ref': None,
                          'acknowledged_at': datetime.now(timezone.utc).isoformat(),
                          'reason': reason, 'previous_draft_ref': old['ref'],
                          'acknowledged_review_ref': old_acceptance.get('acknowledged_review_ref') or old_acceptance.get('review_ref'),
                          'acknowledged_issues': deepcopy(old_acceptance.get('acknowledged_issues', []))}
        run.event('artifact.created', artifact_ref=item['ref'], actor='user', correction=item['correction'])
        run.event('human.accepted', draft_ref=item['ref'], acceptance=deepcopy(run.acceptance),
                  old_acceptance=old_acceptance, reason=reason)
        run.status_version += 1
        encoded = json.dumps(asdict(run), ensure_ascii=False)
        db.execute('UPDATE runs SET payload=? WHERE id=? AND owner=?', (encoded, run_id, owner))
        db.execute('INSERT INTO commands VALUES(?,?,?,?)', (run_id, key, fingerprint, encoded))
        return run
