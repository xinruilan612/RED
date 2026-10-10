"""One-shot synthetic live acceptance; never approve a user's real manuscript.

The caller must supply the existing shared 5-CNY ledger. No automatic retry,
unknown-usage continuation or budget reset is implemented here. Only explicit
resume of a settled, error-free synthetic creation pause is supported.
"""
import argparse
import copy
import base64
import io
import json
import os
import sqlite3
from pathlib import Path
import sys
import time
import threading
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from backend.contracts import DomainError, require, PARAMETERS
from backend.provider import Config, DeepSeek
from backend.service import Service
from backend.store import Store
from backend.worker import Worker
from backend import windtunnel as wt
from scripts.study_budget import BudgetedClient

# Constructed software specimen, not an actual product/official factual source.
MATERIAL = ('合成验收工具“纸舟”版本1.0，只用于本次软件功能测试。'
            '支持UTF-8纯文本输入。操作步骤：打开工具，选择TXT文件，点击导出。'
            '成功时在原文件旁生成result.txt；没有生成时检查原目录写入权限。'
            '工具完全离线，不需要账号；不支持PDF和图片，也没有批量处理功能。')
QUESTION = '操作完成后文件保存在哪里，没生成文件时应先检查什么？'


class SerializedStudyClient:
    """Serialize this experiment's full reservation/request/settlement boundary.

    Production's audience/research remain parallel graph nodes. Only this
    single-inflight shared-budget adapter is serialized, without weakening its
    unknown or total-budget guard. A failed call releases the lock; the next
    caller must still pass the original ledger's unknown check.
    """
    def __init__(self, client):
        self.client = client
        self._lock = threading.Lock()

    def complete_result(self, messages):
        with self._lock:
            return self.client.complete_result(messages)

    def summary(self):
        return self.client.summary()


def credential(path):
    """Extract exactly one literal key; do not load other dotenv settings."""
    found = []
    for line in Path(path).read_text(encoding='utf-8-sig').splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            name, value = line.split('=', 1)
            if name.strip() == 'DEEPSEEK_API_KEY':
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in '\"\'':
                    value = value[1:-1]
                found.append(value)
    require(len(found) == 1 and bool(found[0]) and not any(c.isspace() for c in found[0]), 'CONFIG_INVALID', '凭据文件必须包含唯一有效DEEPSEEK_API_KEY')
    return Config(api_key=found[0], model='deepseek-flash')


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def settlement_guard(store, client, run_id):
    if hasattr(client, 'summary'):
        require(not client.summary()['unknown_calls'], 'STUDY_USAGE_UNKNOWN', '共享账本有未知付费用量，停止验证，不重发')
    with store.connect() as db:
        require(not db.execute('SELECT 1 FROM live_calls WHERE run_id=? AND actual IS NULL', (run_id,)).fetchone(), 'STUDY_USAGE_UNKNOWN', '调用未结算，停止续作')


def advance_settled(service, client, owner, run_id, *, returned=False, on_state=lambda *_: None, on_pause=lambda: None):
    """Bounded advance of settled normal checkpoints; never replay an error."""
    store = service.store
    # Automatic mode intentionally pauses after each completed review.
    # Advance only normal settled checkpoints, under the product's own bounds.
    for segment in range(PARAMETERS['revision_rounds_max'] + 1):
        settlement_guard(store, client, run_id)
        run = store.get(run_id, owner)
        previous_reviews = len(run.reviews)
        state = service.view(run)
        if state['background']['status'] == 'paused':
            normal_revision = (run.current_stage == 'content' and run.review
                               and run.review['decision'] == 'revision_required')
            explicit_return = (returned and segment == 0 and run.current_stage == 'reviewer'
                               and run.review is None and run.drafts
                               and run.drafts[-1].get('source', {}).get('workflow_type') == 'windtunnel')
            require(run.workflow_type == 'creation' and run.run_status == 'RUNNING'
                    and state['background'].get('error') is None and (normal_revision or explicit_return)
                    and run.context.get('runtime_execution', {}).get('mode') in ('automatic', 'revision'),
                    'VALIDATION_BLOCKED', '暂停不满足正常自动续作或显式回写复审条件')
            with store.connect() as db:
                require(not db.execute('SELECT 1 FROM live_calls WHERE run_id=? AND actual IS NULL', (run_id,)).fetchone(), 'STUDY_USAGE_UNKNOWN', '调用未结算，停止续作')
            if normal_revision: on_pause()
        service.background(owner, run_id, {'action': 'start', 'version': run.status_version, 'key': uuid4().hex})
        require(Worker(service).once(), 'VALIDATION_BLOCKED', '后台没有领取验证任务')
        settlement_guard(store, client, run_id)
        run = store.get(run_id, owner); state = service.view(run)
        on_state(run_id, state)
        if state['background']['status'] == 'waiting':
            return run
        require(state['background']['status'] == 'paused' and state['background'].get('error') is None
                and run.run_status == 'RUNNING' and run.workflow_type == 'creation'
                and len(run.reviews) > previous_reviews, 'VALIDATION_BLOCKED', '不是已完成审核的正常暂停；不自动重试')
    raise DomainError('VALIDATION_SEGMENT_LIMIT', '达到产品自动返修分段上限，保留稿件等待人工处理')



def exercise(config, client, output, *, exercise_edit=False, export=True, resume=False):
    """Inject a no-fee test client in unit tests; actual callers use BudgetedClient."""
    original = Path(output)
    resumed_run = None
    prior = None
    if resume:
        require((original / 'study.sqlite').is_file() and (original / 'result.json').is_file(), 'VALIDATION_RESUME_INVALID', '缺少原验证数据库和报告')
        prior = json.loads((original / 'result.json').read_text(encoding='utf-8'))
        require(prior.get('specimen') == 'synthetic_acceptance_only' and prior.get('outcome') == 'blocked'
                and prior.get('error_code') == 'VALIDATION_BLOCKED' and len(prior.get('runs', [])) == 1
                and not (prior.get('budget_after') or {}).get('unknown_calls'), 'VALIDATION_RESUME_INVALID', '仅能恢复已结算的单创作正常暂停')
        # Exclusive, persistent claim: interrupted/unknown resumes cannot be blindly rerun.
        with (original / '.explicit-resume-claimed').open('x', encoding='utf-8') as claim:
            claim.write('explicit synthetic pause resume; do not reset\n')
        output = original / ('resume-' + uuid4().hex[:12])
    else:
        output = original
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    result = {'specimen': 'synthetic_acceptance_only', 'model_alias': config.model,
              'server_model_snapshot': 'unavailable', 'outcome': 'started',
              'ai_patch': 'not_exercised', 'return_review': 'not_exercised',
              'synthetic_acceptance': False, 'human_real_work_approved': False,
              'user_edit': 'not_exercised', 'error_code': None, 'runs': [],
              'model_quality_claim': False, 'artifacts': [], 'material': MATERIAL,
              'normal_pause_continuations': 0}
    client = SerializedStudyClient(client)
    store = Store(original / 'study.sqlite')
    service = Service(store, config, client, allow_windtunnel_live=True)
    if resume:
        with store.connect() as db:
            row = db.execute('SELECT payload FROM runs WHERE id=?', (prior['runs'][0],)).fetchone()
            require(row is not None, 'VALIDATION_RESUME_INVALID', '原创作不存在')
            payload = json.loads(row[0])
        owner = payload['owner_id']
        require(owner.startswith('synthetic-validation-') and payload.get('workflow_type', 'creation') == 'creation'
                and payload['context'].get('material') == MATERIAL, 'VALIDATION_RESUME_INVALID', '不是本脚本的合成创作')
        resumed_run = payload['run_id']
        state = service.view(store.get(resumed_run, owner))
        require(state['run_status'] == 'RUNNING' and state['background']['status'] == 'paused'
                and state['background'].get('error') is None and state['current_stage'] == 'content'
                and (state.get('review') or {}).get('decision') == 'revision_required', 'VALIDATION_RESUME_INVALID', '不是无错误的正常暂停')
        with store.connect() as db:
            require(not db.execute('SELECT 1 FROM live_calls WHERE run_id=? AND actual IS NULL', (resumed_run,)).fetchone(), 'STUDY_USAGE_UNKNOWN', '原任务调用未结算，禁止恢复')
        result.update(resumed_from='result.json', runs=[resumed_run], resume_output=str(output))
    else:
        owner = 'synthetic-validation-' + uuid4().hex
    result['owner_kind'] = 'isolated_test_owner'
    save(output / 'result.json', result)
    account = service.operations.read(owner)['accounts'][0]['id']
    before = client.summary() if hasattr(client, 'summary') else None
    result['budget_before'] = before

    def guard():
        if hasattr(client, 'summary'):
            require(not client.summary()['unknown_calls'], 'STUDY_USAGE_UNKNOWN', '共享账本有未知付费用量，停止验证，不重发')

    def value(run_id):
        return store.get(run_id, owner)

    def action(run_id, name, payload):
        run = value(run_id)
        return service.action(owner, run_id, {'action': name, 'version': run.status_version,
                                            'key': uuid4().hex, 'payload': payload})

    def work(run_id, returned=False):
        def pause(): result['normal_pause_continuations'] += 1
        return advance_settled(service, client, owner, run_id, returned=returned,
                               on_pause=pause, on_state=lambda rid, state: save(output / (rid + '.json'), state))

    def accept_if_approved(run_id):
        run = value(run_id)
        if not (run.run_status == 'WAITING_USER' and run.wait_reason == 'final_confirmation'
                and run.review and run.review['decision'] == 'approved'):
            return False
        action(run_id, 'accept', {'draft_ref': run.drafts[-1]['ref'], 'review_ref': run.review['ref']})
        result['synthetic_acceptance'] = True
        return True

    try:
        guard()
        if resumed_run:
            creation_id = resumed_run
        else:
            created = service.create(owner, {'mode': 'live', 'topic': '纸舟TXT导出：学生一分钟找到结果文件',
                      'audience': '需要导出课堂笔记的学生', 'tone': '简洁准确', 'material': MATERIAL,
                      'allow_hypothesis': True, 'operations': {'account_id': account, 'platform': 'xiaohongshu'}})
            creation_id = created['run_id']; result['runs'].append(creation_id)
        run = work(creation_id)
        require(accept_if_approved(creation_id), 'VALIDATION_REVIEW_NOT_APPROVED', '初稿未审核通过；未强行采用或自动返修')
        imported = service.create(owner, {'workflow_type': 'windtunnel', 'mode': 'live', 'account_id': account,
                 'import': {'run_id': creation_id, 'draft_ref': value(creation_id).drafts[-1]['ref']},
                 'scene': '合成验收样例，学生需要完成TXT导出',
                 'materials': [{'text': MATERIAL, 'title': '合成验收规格', 'origin': 'constructed-test-fixture'}]})
        check_id = imported['run_id']; result['runs'].append(check_id)
        action(check_id, 'set_initial_conditions', {'conditions': [{'question': QUESTION, 'scene': '合成测试', 'origin': 'author', 'source_ids': []}]})
        cs = wt.conditions(value(check_id))
        action(check_id, 'confirm_conditions', {'condition_set_id': cs['id'], 'condition_hash': cs['hash']})
        check = work(check_id)
        report = wt.current_report(check)
        failed = [r['condition_id'] for r in report['results'] if r['status'] != 'pass']
        result['reader_check'] = {'report_id': report['id'], 'statuses': [r['status'] for r in report['results']]}
        modified = False
        if failed:
            action(check_id, 'propose_patch', {'condition_ids': failed})
            check = work(check_id)
            patches = check.windtunnel['patches']
            if patches:
                patch = patches[-1]
                items = [i['id'] for i in patch['items'] if i.get('citations') and not i.get('accepted')]
                if items:
                    action(check_id, 'apply_patch', {'patch_id': patch['id'], 'item_ids': items, 'base_hash': wt.draft(check)['hash']})
                    modified = True; result['ai_patch'] = 'applied_supported_synthetic_patch'
        if not modified and exercise_edit:
            check = value(check_id); draft = wt.draft(check)
            # Explicit function-path exercise, not a claimed AI benefit or hidden repair.
            action(check_id, 'edit_draft', {'title': draft['title'], 'text': '操作清单：\n\n' + draft['text'], 'base_hash': draft['hash']})
            modified = True; result['user_edit'] = 'explicit_synthetic_function_exercise'
        if modified:
            check = value(check_id); draft = wt.draft(check); binding = check.windtunnel['import_binding']
            service.return_to_creation(owner, check_id, {'version': check.status_version, 'key': uuid4().hex,
              'payload': {'draft_id': draft['id'], 'draft_hash': draft['hash'], 'source_run_id': binding['run_id'],
                          'source_draft_ref': binding['draft_ref'], 'source_content_hash': binding['content_hash'],
                          'source_version': binding['source_version']}})
            result['return_review'] = 'returned_review_pending'
            work(creation_id, returned=True)
            require(accept_if_approved(creation_id), 'VALIDATION_REVIEW_NOT_APPROVED', '回写新稿未审核通过；未采用，原历史保留')
            result['return_review'] = 'reviewed_and_synthetically_accepted'
        final = value(creation_id)
        (output / 'final.md').write_text(service.export(owner, creation_id), encoding='utf-8')
        result['artifacts'].append('final.md')
        if export:
            from PIL import Image, ImageDraw
            from backend import posters
            from backend.media_exports import export_run
            image = Image.new('RGB', (720, 720), '#e9edeb')
            ImageDraw.Draw(image).rectangle((120, 160, 600, 560), fill='#3b5a63')
            stream = io.BytesIO(); image.save(stream, format='PNG')
            source = 'data:image/png;base64,' + base64.b64encode(stream.getvalue()).decode()
            draft = final.drafts[-1]
            base = {'draft_ref': draft['ref'], 'content_hash': draft['content_hash']}
            state = posters.mutate(store, owner, creation_id, {**base, 'action': 'init', 'idempotency_key': uuid4().hex})['state']
            state = posters.generate(store, owner, creation_id, {**base, 'expected_revision': state['revision'], 'idempotency_key': uuid4().hex, 'style': 'minimal', 'brief': '', 'source_image': source})['state']
            state = posters.mutate(store, owner, creation_id, {**base, 'action': 'accept', 'expected_revision': state['revision'], 'idempotency_key': uuid4().hex})['state']
            raw, _, _ = posters.export(store, owner, creation_id, {**base, 'expected_revision': state['revision'], 'format': 'png'})
            (output / 'synthetic-poster.png').write_bytes(raw)
            raw, _, _ = export_run(final, kind='images', template='classic')
            (output / 'full-copy-images.zip').write_bytes(raw)
            result['artifacts'] += ['synthetic-poster.png', 'full-copy-images.zip']
        result['outcome'] = 'completed'
    except Exception as error:
        result['outcome'] = 'blocked'
        result['error_code'] = error.code if isinstance(error, DomainError) else 'VALIDATION_INTERNAL_ERROR'
        # No raw exception/credentials in report; run JSON and call ledger preserve diagnostics.
    finally:
        for run_id in result['runs']:
            save(output / (run_id + '.json'), service.view(value(run_id)))
        result['budget_after'] = client.summary() if hasattr(client, 'summary') else None
        result['elapsed_seconds'] = round(time.monotonic() - started, 3)
        save(output / 'result.json', result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--credential-file', required=True)
    parser.add_argument('--budget-ledger', required=True)
    destination = parser.add_mutually_exclusive_group(required=True)
    destination.add_argument('--output-dir')
    destination.add_argument('--resume-validation', help='仅恢复单创作合成验收的已结算正常暂停，不覆盖原报告')
    parser.add_argument('--exercise-edit', action='store_true', help='明确执行合成人工改句功能验证，不算AI修改收益')
    args = parser.parse_args(argv)
    os.environ['YOUJI_IGNORE_PROJECT_ENV'] = '1'
    try:
        output = Path(args.resume_validation or args.output_dir).resolve()
        require(output.is_relative_to(ROOT / 'runtime'), 'INVALID_INPUT', '验证结果必须存本工作树runtime新目录')
        ledger = Path(args.budget_ledger).resolve()
        require(ledger.is_file(), 'STUDY_BUDGET_INVALID', '必须使用既有共享账本，不新开或重置')
        with sqlite3.connect('file:' + ledger.as_posix() + '?mode=ro', uri=True) as db:
            existing = db.execute('SELECT cap_micro FROM study_budget WHERE id=1').fetchone()
            require(existing is not None and existing[0] == 5_000_000, 'STUDY_BUDGET_INVALID', '必须沿用既有总5元账本，不能新建预算')
        config = credential(args.credential_file)
        client = BudgetedClient(DeepSeek(config), ledger, cap_cny=5, continue_after_unknown=False)
        report = exercise(config, client, output, exercise_edit=args.exercise_edit, resume=bool(args.resume_validation))
        print(json.dumps({k: report[k] for k in ('specimen', 'outcome', 'error_code', 'ai_patch', 'return_review', 'budget_after')}, ensure_ascii=False))
        return 0 if report['outcome'] == 'completed' else 1
    except Exception as error:
        print(json.dumps({'outcome': 'not_started', 'error_code': error.code if isinstance(error, DomainError) else 'VALIDATION_CONFIG_ERROR'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
