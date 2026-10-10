"""Pure workflow guards. Repository transaction owns all mutations and identity."""
import hashlib
import json
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional
from uuid import uuid4

from backend.contracts import CONTRACT, PARAMETERS, require, integer


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


@dataclass
class Run:
    owner_id: str
    snapshot_id: str
    run_id: str = field(default_factory=lambda: str(uuid4()))
    schema_version: int = 2
    run_status: str = 'QUEUED'
    current_stage: str = 'brief'
    wait_reason: Optional[str] = None
    status_version: int = 0
    iteration: int = 0
    supplements: int = 0
    context: dict = field(default_factory=dict)
    artifacts: list = field(default_factory=list)
    node_runs: list = field(default_factory=list)
    reviews: list = field(default_factory=list)
    branches: dict = field(default_factory=dict)
    branch_errors: dict = field(default_factory=dict)
    drafts: list = field(default_factory=list)
    review: Optional[dict] = None
    prior_review: Optional[dict] = None
    accepted_ref: Optional[str] = None
    acceptance: Optional[dict] = None
    events: list = field(default_factory=list)
    workflow_type: str = 'creation'
    windtunnel: dict = field(default_factory=dict)

    def event(self, kind, **payload):
        require(kind in CONTRACT['events'], 'INVALID_EVENT', kind)
        self.events.append({'schema_version': 2, 'event_id': str(uuid4()),
                            'run_id': self.run_id, 'seq': len(self.events) + 1,
                            'occurred_at': datetime.now(timezone.utc).isoformat(),
                            'type': kind, 'payload': payload})

    def _transition(self, target, reason=None):
        require(target in CONTRACT['transitions'][self.run_status], 'INVALID_TRANSITION',
                f'{self.run_status} -> {target}')
        if target == 'WAITING_USER':
            require(reason in CONTRACT['wait_reasons'], 'INVALID_INPUT', '等待原因无效')
        self.run_status, self.wait_reason = target, reason
        self.event('workflow.transition', run_status=target, wait_reason=reason)

    def start(self):
        self._transition('RUNNING')
        self.event('run.started')

    def cancel(self):
        self._transition('CANCELLED')
        self.event('run.cancelled')

    def branch(self, agent, snapshot_id, outcome, data=None):
        require(self.run_status == 'RUNNING' and self.current_stage == 'brief',
                'INVALID_TRANSITION', '当前不可接收分支')
        require(agent in CONTRACT['join_requires'], 'INVALID_INPUT', '无效分支')
        require(snapshot_id == self.snapshot_id, 'VERSION_CONFLICT', '分支快照过期')
        require(agent not in self.branches, 'VERSION_CONFLICT', '分支已提交')
        require(outcome in ('succeeded', 'retryable_error', 'failed'), 'INVALID_INPUT', '分支状态无效')
        if outcome != 'succeeded':
            self.branch_errors[agent] = self.branch_errors.get(agent, 0) + 1
            retryable = outcome == 'retryable_error' and self.branch_errors[agent] <= PARAMETERS['transport_retries_max']
            self._transition('RETRY_WAIT' if retryable else 'FAILED')
            self.event('agent.failed', agent=agent)
            return
        require(isinstance(data, dict), 'INVALID_INPUT', '成功分支必须提供资料')
        if agent == 'audience':
            integer(data.get('sample_size'), 'sample_size')
        if agent == 'research':
            require(type(data.get('core_gap')) is bool, 'INVALID_INPUT', 'core_gap 必须经上层判断')
        self.branches[agent] = {'snapshot_id': snapshot_id, 'data': data}
        self.event('branch.completed', agent=agent)

    def retry(self):
        require(self.run_status == 'RETRY_WAIT', 'INVALID_TRANSITION', '仅可重试等待中的任务')
        self._transition('QUEUED')
        # Successful sibling remains; budgets are owned by the same repository run.

    def join(self, allow_hypothesis):
        require(type(allow_hypothesis) is bool, 'INVALID_INPUT', '必须明确假设授权')
        require(self.run_status == 'RUNNING' and self.current_stage == 'brief', 'INVALID_TRANSITION', '不能汇合')
        require(set(self.branches) == set(CONTRACT['join_requires']), 'JOIN_INCOMPLETE', '等待两个分支')
        require(all(b['snapshot_id'] == self.snapshot_id for b in self.branches.values()),
                'VERSION_CONFLICT', '分支版本不一致')
        if not self.branches['audience']['data']['sample_size'] and not allow_hypothesis:
            self._transition('WAITING_USER', 'hypothesis_permission')
        elif self.branches['research']['data']['core_gap']:
            self._transition('WAITING_USER', 'missing_material')
        else:
            self.current_stage = 'content'
            self.event('join.completed')

    def supplement(self, snapshot_id):
        require(self.run_status == 'WAITING_USER' and self.wait_reason in ('missing_material', 'hypothesis_permission'),
                'INVALID_TRANSITION', '当前不能补料恢复')
        require(self.supplements < PARAMETERS['supplement_rounds_max'], 'SUPPLEMENT_LIMIT', '补研究次数已用完')
        require(isinstance(snapshot_id, str) and snapshot_id and snapshot_id != self.snapshot_id,
                'VERSION_CONFLICT', '必须生成新的输入快照')
        self.supplements += 1
        self.snapshot_id, self.branches, self.review = snapshot_id, {}, None
        self.prior_review, self.branch_errors = None, {}
        self.current_stage = 'brief'
        self._transition('QUEUED')

    def draft(self, content):
        require(self.run_status == 'RUNNING' and self.current_stage == 'content', 'INVALID_TRANSITION', '当前不能提交稿件')
        require(isinstance(content, dict) and isinstance(content.get('body'), str) and content['body'].strip(),
                'INVALID_INPUT', '正文不能为空')
        item = {'ref': f'{uuid4()}@1', 'content': json.loads(json.dumps(content)),
                'content_hash': digest(content), 'snapshot_id': self.snapshot_id, 'actor':'content'}
        self.drafts.append(item)
        self.prior_review = self.review
        self.review = None
        self.current_stage = 'reviewer'
        self.event('artifact.created', artifact_ref=item['ref'])
        return item['ref']

    def reviewed(self, report, gates, fail_on_limit=False):
        require(self.run_status == 'RUNNING' and self.current_stage == 'reviewer' and self.drafts,
                'INVALID_TRANSITION', '当前不能接收审核')
        validate_review(report, self.drafts[-1], gates, self.prior_review)
        self.review = json.loads(json.dumps(report))
        self.reviews.append(json.loads(json.dumps(report)))
        self.event('review.completed', decision=report['decision'])
        if report['decision'] == 'approved':
            self._transition('WAITING_USER', 'final_confirmation')
        elif report['decision'] == 'needs_human':
            self._transition('WAITING_USER', 'missing_material')
        elif self.iteration >= PARAMETERS['revision_rounds_max']:
            if fail_on_limit:
                self._transition('FAILED')
                self.event('agent.failed',agent='reviewer',mode='live',message='初稿及5次改稿仍未通过审核，已达到改稿上限；停止调用')
            else:
                self._transition('WAITING_USER', 'revision_limit')
        else:
            self.iteration += 1
            self.current_stage = 'content'

    def accept(self, draft_ref, review_ref):
        require(self.run_status == 'WAITING_USER' and self.wait_reason == 'final_confirmation',
                'INVALID_TRANSITION', '必须先通过审核')
        require(self.review and self.review['decision'] == 'approved', 'REVIEW_REQUIRED', '没有有效审核')
        draft = self.drafts[-1]
        require(draft['ref'] == draft_ref == self.review['draft_ref'] and self.review['ref'] == review_ref
                and draft['snapshot_id'] == self.snapshot_id
                and self.review['content_hash'] == digest(draft['content']),
                'VERSION_CONFLICT', '确认的稿件或审核已失效')
        # Explicit queued/running transitions preserve the approved lifecycle graph.
        self._transition('QUEUED')
        self._transition('RUNNING')
        self.acceptance = {'mode':'reviewed','draft_ref':draft_ref,'content_hash':draft['content_hash'],
                           'snapshot_id':self.snapshot_id,'review_ref':review_ref}
        self.accepted_ref = draft_ref
        self.event('human.accepted', draft_ref=draft_ref)
        self._transition('SUCCEEDED')
        self.event('run.completed')

    def can_manual_adopt(self):
        if self.workflow_type != 'creation' or not self.drafts:
            return False
        draft = self.drafts[-1]
        if draft['snapshot_id'] != self.snapshot_id:
            return False
        return (self.run_status == 'WAITING_USER' and self.wait_reason in
                ('final_confirmation', 'missing_material', 'revision_limit')) or (
                self.run_status == 'RUNNING' and self.current_stage in ('content', 'reviewer'))

    def adopt_manual(self, draft_ref, content_hash, acknowledge):
        require(acknowledge is True, 'INVALID_INPUT', '请明确知晓审核问题后采用')
        require(self.can_manual_adopt(), 'INVALID_TRANSITION', '当前不能人工采用稿件')
        draft = self.drafts[-1]
        require(not (self.review and self.review.get('decision') == 'approved'),
                'INVALID_TRANSITION', '审核已通过，请使用确认当前版本')
        require(draft_ref == draft['ref'] and content_hash == draft['content_hash'] == digest(draft['content']),
                'VERSION_CONFLICT', '采用的稿件版本已失效')
        report = self.review or self.prior_review
        self.acceptance = {'mode':'manual_override','draft_ref':draft_ref,'content_hash':content_hash,
                           'snapshot_id':self.snapshot_id,
                           'review_ref':self.review['ref'] if self.review else None,
                           'acknowledged_review_ref':report['ref'] if report else None,
                           'acknowledged_issues':json.loads(json.dumps([i for i in (report or {}).get('issues', []) if i.get('state') != 'resolved'])),
                           'acknowledged_at':datetime.now(timezone.utc).isoformat()}
        if self.run_status == 'WAITING_USER':
            self._transition('QUEUED')
            self._transition('RUNNING')
        self.accepted_ref = draft_ref
        self.event('human.accepted', draft_ref=draft_ref, acceptance=self.acceptance)
        self._transition('SUCCEEDED')
        self.event('run.completed', acceptance_mode='manual_override')

    def edit(self, content):
        require(self.can_manual_adopt(), 'INVALID_TRANSITION', '当前不能编辑稿件')
        if self.run_status == 'WAITING_USER':
            self._transition('QUEUED')
            self._transition('RUNNING')
        self.current_stage = 'content'
        prior = self.review or self.prior_review
        ref = self.draft(content)
        self.prior_review = prior
        self.drafts[-1]['actor'] = 'user'
        return ref

    def demo_step(self):
        from backend.demo import advance
        advance(self)

    def demo_supplement(self, material, allow_hypothesis):
        from backend.demo import validate_text
        validate_text(material, '补充素材', 8000, allow_empty=True)
        require(type(allow_hypothesis) is bool, 'INVALID_INPUT', '请选择假设授权')
        if self.wait_reason == 'missing_material':
            require(material.strip(), 'INVALID_INPUT', '请补充实际素材')
        if self.wait_reason == 'hypothesis_permission':
            require(allow_hypothesis, 'INVALID_INPUT', '当前没有可用受众历史，请明确允许将受众判断作为待验证假设，或补充真实历史后重新开始')
        self.supplement(str(uuid4()))
        self.context['material'] = material
        self.context['allow_hypothesis'] = allow_hypothesis
        self.artifacts = []



def validate_review(report, draft, gates, previous=None):
    """gates are trusted service results, not fields accepted from model/browser."""
    require(isinstance(report, dict) and isinstance(gates, dict), 'MODEL_OUTPUT_INVALID', '审核格式无效')
    policy = CONTRACT['review_policy']
    require(set(gates) == set(policy['required_gates']) and all(v is True for v in gates.values()),
            'REVIEW_GATE_FAILED', '确定性检查未通过')
    require(report.get('draft_ref') == draft['ref'] and report.get('content_hash') == draft['content_hash']
            and report.get('snapshot_id') == draft['snapshot_id'], 'VERSION_CONFLICT', '审核版本不一致')
    require(isinstance(report.get('ref'), str) and report['ref'] and isinstance(report.get('policy_ref'), str)
            and report['policy_ref'], 'MODEL_OUTPUT_INVALID', '缺少审核或规则引用')
    checks = report.get('checks')
    require(isinstance(checks, list) and all(isinstance(x, dict) for x in checks), 'MODEL_OUTPUT_INVALID', '缺少检查项')
    require(len(checks) == len(policy['checks']) and {c.get('name') for c in checks} == set(policy['checks']),
            'MODEL_OUTPUT_INVALID', '检查项缺失或重复')
    require(all(c.get('result') in ('pass', 'fail', 'unknown') for c in checks), 'MODEL_OUTPUT_INVALID', '检查结果无效')
    issues = report.get('issues')
    require(isinstance(issues, list) and all(isinstance(i, dict) for i in issues), 'MODEL_OUTPUT_INVALID', '缺少问题列表')
    ids = [i.get('issue_id') for i in issues]
    require(all(isinstance(i, str) and i for i in ids) and len(set(ids)) == len(ids), 'MODEL_OUTPUT_INVALID', '问题 ID 无效')
    require(all(i.get('severity') in ('blocker','major','minor') and i.get('state') in ('open','resolved') for i in issues),
            'MODEL_OUTPUT_INVALID', '问题严重度或状态无效')
    old_results = report.get('previous_issue_results', [])
    require(isinstance(old_results, list) and all(isinstance(i, dict) for i in old_results), 'MODEL_OUTPUT_INVALID', '旧问题结果无效')
    old_issues = previous['issues'] if previous else []
    require(len(old_results) == len(old_issues) and {i.get('issue_id') for i in old_results} == {i['issue_id'] for i in old_issues},
            'MODEL_OUTPUT_INVALID', '旧问题必须逐项复核')
    require(all(i.get('result') in ('resolved','unresolved','regressed') for i in old_results), 'MODEL_OUTPUT_INVALID', '复核结果无效')
    decisions = {'approved':'await_user_confirmation','revision_required':'revise','needs_human':'request_human'}
    decision = report.get('decision')
    require(decision in decisions and report.get('next_action') == decisions[decision], 'MODEL_OUTPUT_INVALID', '决定与动作不一致')
    if decision == 'approved':
        results = {c['name']:c['result'] for c in checks}
        require(all(results[n] == 'pass' for n in policy['required_pass']), 'REVIEW_GATE_FAILED', '必需检查未通过')
        require(results['originality_risk'] == 'pass' or (results['originality_risk'] == 'unknown'
                and isinstance(report.get('limitations'), list) and any(isinstance(x,str) and x.strip() for x in report['limitations'])),
                'REVIEW_GATE_FAILED', '原创检查未完成且未说明限制')
        require(not any(i['severity'] in policy['blocking_severities'] and i['state'] == 'open' for i in issues),
                'REVIEW_GATE_FAILED', '仍有重要问题')
        important = {i['issue_id'] for i in old_issues if i['severity'] in policy['blocking_severities']}
        require(all(i['result'] == 'resolved' for i in old_results if i['issue_id'] in important), 'REVIEW_GATE_FAILED', '旧重要问题未解决')
    if decision == 'revision_required':
        require(any(i['state'] == 'open' for i in issues), 'MODEL_OUTPUT_INVALID', '缺少改稿问题')
    if decision == 'needs_human':
        require(isinstance(report.get('human_questions'), list) and any(isinstance(x,str) and x.strip() for x in report['human_questions']),
                'MODEL_OUTPUT_INVALID', '缺少人工处理问题')
