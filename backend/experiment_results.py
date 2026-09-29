"""Server-validated experiment publication binding and descriptive observation."""
import copy
from uuid import uuid4

from backend.analytics import latest_metrics, window_quality
from backend.contracts import require
from backend.experiments import active_experiment, decision_snapshot, default_format, reward
from backend.workflow import digest


def invalidate_results(state, reason, experiment_id=None, publication_id=None, window=None):
    for result in state.get('experiment_results', []):
        if (result['status'] != 'superseded' and
                (experiment_id is None or result['experiment_id'] == experiment_id) and
                (publication_id is None or result['publication_id'] == publication_id) and
                (window is None or result['window'] == window)):
            result['status'] = 'superseded'
            result['invalid_reason'] = reason


def prepare_binding(state, run, publication):
    op = run.context.get('operations', {})
    snapshot = op.get('experiment')
    if snapshot is None:
        return
    require(isinstance(snapshot, dict), 'INVALID_INPUT', '实验上下文无效')
    require(run.context.get('mode') in ('simulation', 'live') and op.get('account_id') == publication['account_id'],
            'INVALID_INPUT', '实验任务账号或运行模式无效')
    experiment = active_experiment(state, snapshot.get('id'), publication['account_id'], publication['platform'],
                                   publication['provenance'], publication['format'], snapshot)
    require(not experiment.get('publication_id') and not any(p.get('experiment_id') == experiment['id']
            for p in state['publications']), 'DUPLICATE', '此实验已绑定发布记录；请前往原发布记录继续')
    publication.update(experiment_id=experiment['id'],
                       experiment_snapshot=decision_snapshot(experiment) | {'decision_hash': experiment['decision_hash']},
                       metadata_confirmed=False, metadata_revision=0)
    experiment['publication_id'] = publication['id']
    invalidate_results(state, '实验已进入发布准备，请更新观测', experiment_id=experiment['id'])


def validate_publication(state, publication):
    if not publication.get('experiment_id'):
        return
    snapshot = publication.get('experiment_snapshot')
    require(isinstance(snapshot, dict), 'VERSION_CONFLICT', '发布记录缺少冻结实验依据')
    experiment = active_experiment(state, publication['experiment_id'], publication['account_id'],
                                   publication['platform'], publication['provenance'], publication['format'], snapshot)
    require(experiment.get('publication_id') == publication['id'], 'VERSION_CONFLICT', '实验发布绑定不一致')
    require((publication['mode'] == 'simulation') == (experiment['source_type'] == 'simulation'),
            'INVALID_INPUT', '实验与发布运行来源不一致')


def evaluate(state, identity, created_at):
    experiment = next((row for row in state['experiments'] if row['id'] == identity), None)
    require(experiment is not None, 'RESOURCE_NOT_FOUND', '实验不可访问')
    publication = next((row for row in state['publications'] if row['id'] == experiment.get('publication_id')), None)
    metric = latest_metrics(state).get((publication['id'], experiment['window'])) if publication else None
    baseline = experiment.get('baseline_reward')
    refs = copy.deepcopy(experiment.get('baseline_metric_refs', []))
    actual = ({key: publication.get(key) for key in ('format', 'pillar', 'traffic', 'metadata_confirmed',
               'metadata_revision', 'status', 'published_at')} if publication else None)
    status, reason, observed, difference = 'pending_publication', '请先按实验创作并完成发布', None, None
    if experiment['status'] != 'accepted' or experiment.get('schema_version') != 2:
        status, reason = 'blocked', experiment.get('invalid_reason') or '实验未接受、已撤销或需要重新生成'
    elif publication:
        try:
            # After publication, users may correct actual metadata truthfully; it
            # is evaluated as a deviation rather than rewriting the frozen plan.
            planned = dict(publication, format=(publication.get('experiment_snapshot') or {}).get('format'))
            validate_publication(state, planned)
        except ValueError:
            status, reason = 'blocked', '发布绑定或实验依据不再有效'
        else:
            if publication['status'] not in ('SIMULATED', 'MANUAL_REPORTED') or not publication.get('published_at'):
                status, reason = 'pending_publication', '已准备稿件，尚未完成发布'
            elif not publication.get('metadata_confirmed'):
                status, reason = 'conditions_mismatch', '请显式记录实际内容形式、栏目和流量类型；不以建议代替实际执行'
            elif (publication['format'] != experiment['format'] or publication['pillar'] != experiment['chosen_pillar']
                  or publication['traffic'] != 'organic'):
                status, reason = 'conditions_mismatch', '实际形式、栏目或自然流量条件与实验约定不同'
            elif not metric:
                status, reason = 'pending_metrics', '尚无目标 ' + experiment['window'] + ' 观察窗口的指标'
            elif (metric['account_id'], metric['platform'], metric['source_type']) != (
                    experiment['account_id'], experiment['platform'], experiment['source_type']):
                status, reason = 'blocked', '观测指标与实验账号、平台或来源不一致'
            elif window_quality(publication, metric)[0] != 'comparable':
                status, reason = 'window_mismatch', '实际观察时长未到目标窗口或已超出窗口容差'
            elif reward(metric) is None:
                status, reason = 'incomplete', '请补齐非零阅读/播放及全部互动指标；缺失不能记为零'
            else:
                observed = reward(metric)
                if baseline is None:
                    status, reason = 'observed_no_baseline', '已记录完整观测；建议时所选栏目没有可比基线，不能计算差值'
                else:
                    status, reason = 'observed', '与建议时冻结的同栏目历史均值作描述性比较，不是因果或显著性结论'
                    difference = round(observed - baseline, 3)
    fingerprint = digest(dict(decision=experiment.get('decision_hash'), status=status, reason=reason,
                              publication_id=publication['id'] if publication else None, actual=actual,
                              metric=metric, baseline=baseline, baseline_refs=refs))
    rows = state.setdefault('experiment_results', [])
    previous = next((row for row in rows if row['experiment_id'] == identity and
                     row['status'] != 'superseded' and row['input_hash'] == fingerprint), None)
    if previous:
        return previous
    invalidate_results(state, '已按新状态重新计算，旧观测保留审计', experiment_id=identity)
    result = dict(id=str(uuid4()), experiment_id=identity, publication_id=publication['id'] if publication else None,
                  account_id=experiment['account_id'], platform=experiment['platform'],
                  source_type=experiment['source_type'], format=experiment.get('format', default_format(experiment['platform'])),
                  window=experiment['window'], status=status, reason=reason, invalid_reason='', created_at=created_at,
                  metric_id=metric['id'] if metric else None, metric_revision=metric['revision'] if metric else None,
                  metric_snapshot=copy.deepcopy(metric), actual=actual, decision_hash=experiment.get('decision_hash'),
                  observed_reward=observed, baseline_reward=baseline, baseline_metric_refs=refs,
                  difference=difference, input_hash=fingerprint,
                  limitations=['仅为用户记录的描述性观测，不证明因果、统计显著或稳定增长。',
                               '实际条件由用户显式申报，未独立核实是否只改变一个变量。',
                               '模拟与人工记录分开；基线固定于建议时，不吸收未来样本。'])
    rows.insert(0, result)
    return result
