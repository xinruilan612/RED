"""Opt-in, bounded snapshots of observed public-note questions. No network calls."""
import json
import re
from datetime import datetime, timezone
from backend.contracts import require
from backend.workflow import digest
from backend.xhs_sync import XHSSync

MAX_NOTES = 3
MAX_SAMPLES = 50
MAX_CHARS = 4000


def redact(text):
    # Strip common contact identifiers; retain ordinary numbers, units and URLs.
    text = str(text).replace('\x00', '').replace('\r\n', '\n')
    text = re.sub(r'(?<!\w)[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', '[邮箱已隐藏]', text)
    text = re.sub(r'(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)', '[手机号已隐藏]', text)
    text = re.sub(r'(?<!\w)@[\w\u3400-\u9fff-]+', '[用户已隐藏]', text)
    return text.strip()[:600]


def freeze(store, owner, account_id, selection):
    selection = {'enabled': False} if selection is None else selection
    require(isinstance(selection, dict) and set(selection) <= {'enabled', 'note_ids'}
            and type(selection.get('enabled')) is bool, 'INVALID_INPUT', '请选择是否参考评论')
    ids = selection.get('note_ids', [])
    require(isinstance(ids, list) and len(ids) <= MAX_NOTES
            and all(isinstance(i, str) and 0 < len(i) <= 200 for i in ids)
            and len(set(ids)) == len(ids), 'INVALID_INPUT', '最多选择 3 篇不同的公开笔记')
    if not selection['enabled']:
        require(not ids, 'INVALID_INPUT', '关闭评论参考时不能选择笔记')
        return {'enabled': False, 'note_ids': [], 'notes': [], 'samples': []}
    require(account_id and ids, 'INVALID_INPUT', '请先选择当前账号的公开笔记；也可以关闭评论参考')
    notes, samples = [], []
    with store.connect() as db:
        db.execute('BEGIN')
        for note_id in ids:
            XHSSync.require_public_note(db, owner, account_id, note_id)
            row = db.execute("SELECT payload,last_seen FROM xhs_sync_entities WHERE owner=? AND account_id=? AND kind='note' AND id=?",
                             (owner, account_id, note_id)).fetchone()
            require(row is not None, 'RESOURCE_NOT_FOUND', '笔记暂无已保存评论来源，请刷新同步状态或关闭评论参考')
            note = json.loads(row[0])
            notes.append({'note_id': note_id, 'title': redact(note.get('title', '')),
                          'url': note.get('url'), 'observed_at': row[1]})
            prefix = note_id + ':'
            rows = db.execute("SELECT payload,first_seen,last_seen FROM xhs_sync_entities WHERE owner=? AND account_id=? AND kind='comment' AND substr(id,1,?)=? ORDER BY last_seen DESC,id LIMIT ?",
                              (owner, account_id, len(prefix), prefix, MAX_SAMPLES)).fetchall()
            # Interleave notes below so a busy first note cannot exclude all others.
            note_samples = []
            for payload, first_seen, last_seen in rows:
                comment = json.loads(payload)
                text = redact(comment.get('content', ''))
                if not text:
                    continue
                note_samples.append({'source_id': 'comment:' + digest([note_id, comment.get('id'), text])[:24],
                                     'note_id': note_id, 'text': text,
                                     'first_seen': first_seen, 'observed_at': last_seen})
            samples.append(note_samples)
    balanced, remaining = [], MAX_CHARS
    candidates = [items[i] for i in range(MAX_SAMPLES) for items in samples if i < len(items)][:MAX_SAMPLES]
    for sample in candidates:
        if remaining <= 0:break
        excerpt = sample['text'][:remaining]
        balanced.append({**sample, 'text': excerpt, 'truncated': len(excerpt) < len(sample['text'])})
        remaining -= len(excerpt)
    return {'enabled': True, 'account_id': account_id, 'note_ids': ids, 'notes': notes,
            'samples': balanced, 'sample_size': len(balanced),
            'context_chars': MAX_CHARS-remaining, 'limits': {'samples': MAX_SAMPLES, 'chars': MAX_CHARS},
            'frozen_at': datetime.now(timezone.utc).isoformat(),
            'coverage': 'historically_observed_not_complete',
            'limitation': '仅选定公开笔记已取得的部分评论，已移除作者字段及常见联系方式；问题不证明产品事实，也不代表全部粉丝偏好。' if balanced else
                          '选定笔记暂无已取得的评论样本；不代表平台没有评论，不生成假评论。'}


def assert_visible(run, db):
    feedback = run.context.get('comment_feedback', {})
    if not feedback.get('enabled'):
        return
    account = run.context.get('operations', {}).get('account_id')
    require(account and account == feedback.get('account_id'), 'RESOURCE_NOT_FOUND', '评论来源账号已失效')
    for note_id in feedback['note_ids']:
        XHSSync.require_public_note(db, run.owner_id, account, note_id)
