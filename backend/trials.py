"""Account-scoped intent signals and staged, evidence-labelled content trials."""
from uuid import uuid4

from backend.contracts import require, integer
from backend.demo import validate_text
from backend.workflow import digest

OBJECTIVES = ('sales', 'audience_growth', 'lead_acquisition')
OBJECTIVE_METRICS = {
    'sales': ('orders',),
    'audience_growth': ('new_followers',),
    'lead_acquisition': ('qualified_leads', 'signups'),
}
OBJECTIVE_DENOMINATORS = {'sales': 'link_clicks', 'audience_growth': 'views', 'lead_acquisition': 'link_clicks'}
LEVELS = ('windtunnel', 'small_race', 'live_attribution')


def _account(state, identity):
    from backend.accounts import find_account
    return find_account(state, identity)


def _hypothesis(state, identity):
    return next((h for h in state['hypotheses'] if h['id'] == identity), None)


def apply(operations, db, owner, state, action, data):
    """Apply a trial command inside the caller's versioned owner transaction."""
    from backend.operations import item, now, timestamp

    if action == 'add_signal':
        require(set(data) == {'account_id', 'kind', 'text', 'source_url', 'observed_at', 'sample_size', 'collection_method', 'notes'},
                'INVALID_INPUT', '需求信号字段无效')
        account = _account(state, data['account_id'])
        require(data['kind'] in ('comment_demand', 'search_intent'), 'INVALID_INPUT', '请选择评论需求或搜索意图')
        require(data['collection_method'] in ('manual', 'public_source', 'authorized_export'), 'INVALID_INPUT', '采集方式无效')
        text = validate_text(data['text'], '信号内容', 1500)
        observed = timestamp(data['observed_at'])
        sample_size = integer(data['sample_size'], '样本数', 1)
        require(sample_size <= 10000000, 'INVALID_INPUT', '样本数超出范围')
        source = data['source_url']
        if source:
            source = operations_source_url(source)
        notes = validate_text(data['notes'], '采集说明', 500, True)
        require(data['collection_method'] != 'public_source' or source, 'INVALID_INPUT', '公开来源需填写来源链接')
        require(not any(s['account_id'] == account['id'] and s['kind'] == data['kind'] and s['text'] == text and s['observed_at'] == observed for s in state['signals']),
                'DUPLICATE', '相同时间和内容的信号已记录')
        state['signals'].insert(0, dict(id=str(uuid4()), account_id=account['id'], platform=account['platform'],
            kind=data['kind'], text=text, source_url=source, observed_at=observed, sample_size=sample_size,
            collection_method=data['collection_method'], notes=notes, provenance='user_recorded', created_at=now()))
        return

    if action == 'create_hypothesis':
        require(set(data) == {'account_id', 'objective', 'audience', 'statement', 'desired_action', 'metric', 'window', 'minimum_lift_pct', 'falsifier', 'signal_ids'},
                'INVALID_INPUT', '假设卡字段无效')
        account = _account(state, data['account_id'])
        require(data['objective'] in OBJECTIVES, 'INVALID_INPUT', '推广目标无效')
        require(data['metric'] in OBJECTIVE_METRICS[data['objective']], 'INVALID_INPUT', '主要指标与推广目标不匹配')
        require(data['window'] in ('24h', '72h', '7d'), 'INVALID_INPUT', '主要观察窗口无效')
        audience = validate_text(data['audience'], '目标受众', 300)
        statement = validate_text(data['statement'], '可证伪假设', 1200)
        desired_action = validate_text(data['desired_action'], '期望行动', 300)
        falsifier = validate_text(data['falsifier'], '反证条件', 600)
        lift = integer(data['minimum_lift_pct'], '最低提升百分比', 1)
        require(lift <= 1000, 'INVALID_INPUT', '最低提升百分比超出范围')
        signal_ids = data['signal_ids']
        require(isinstance(signal_ids, list) and 1 <= len(signal_ids) <= 20 and len(signal_ids) == len(set(signal_ids)), 'INVALID_INPUT', '请关联 1 至 20 条不同的需求信号')
        signals = [item(state['signals'], signal_id) for signal_id in signal_ids]
        require(all(s['account_id'] == account['id'] and s['platform'] == account['platform'] for s in signals), 'RESOURCE_NOT_FOUND', '信号不属于该账号与平台')
        require(not any(h['account_id'] == account['id'] and h['statement'] == statement and h['status'] not in ('rejected', 'revoked') for h in state['hypotheses']),
                'DUPLICATE', '该假设已存在')
        record = dict(id=str(uuid4()), account_id=account['id'], platform=account['platform'], objective=data['objective'],
            audience=audience, statement=statement, desired_action=desired_action, metric=data['metric'],
            denominator=OBJECTIVE_DENOMINATORS[data['objective']], window=data['window'], minimum_lift_pct=lift, falsifier=falsifier,
            signal_refs=[dict(id=s['id'], kind=s['kind'], observed_at=s['observed_at'], sample_size=s['sample_size']) for s in signals],
            created_at=now(), version=1, status='testing', validations={}, verdict=None, ledger_status=None, revision_hash='')
        record['revision_hash'] = digest({k: v for k, v in record.items() if k not in ('created_at', 'revision_hash')})
        state['hypotheses'].insert(0, record)
        return

    if action == 'record_trial':
        require(set(data) == {'hypothesis_id', 'level', 'payload'}, 'INVALID_INPUT', '验证记录字段无效')
        hypothesis = _hypothesis(state, data['hypothesis_id'])
        require(hypothesis is not None, 'RESOURCE_NOT_FOUND', '假设卡不可访问')
        require(hypothesis['status'] == 'testing', 'INVALID_TRANSITION', '已归档或撤销的假设不能继续验证')
        require(data['level'] in LEVELS and isinstance(data['payload'], dict), 'INVALID_INPUT', '验证阶段无效')
        level = data['level']
        stage_index = LEVELS.index(level)
        direct_reader_test = level == 'small_race' and 'reader_feedback' in data['payload']
        if level == 'live_attribution':
            require('small_race' in hypothesis['validations'], 'INVALID_TRANSITION', '请先完成真实读者比较，再关联发布结果')
        elif not direct_reader_test:
            require(all(LEVELS[i] in hypothesis['validations'] for i in range(stage_index)), 'INVALID_TRANSITION', '请先完成 AI 检查，或直接记录真人试读反馈')
        require(level not in hypothesis['validations'], 'DUPLICATE', '该阶段已有记录；如数据有误请撤销假设并新建版本')
        if level == 'windtunnel':
            validation = _record_windtunnel(operations, db, owner, hypothesis, data['payload'], now)
        elif level == 'small_race':
            validation = _record_race(operations, db, owner, hypothesis, data['payload'], now, timestamp)
        else:
            validation = _record_attribution(operations, db, owner, state, hypothesis, data['payload'], now, timestamp)
        validation['level'] = level
        hypothesis['validations'][level] = validation
        if level == 'live_attribution':
            hypothesis['status'] = 'awaiting_review'
        return

    if action == 'decide_hypothesis':
        require(set(data) == {'hypothesis_id', 'verdict', 'notes'}, 'INVALID_INPUT', '经验裁决字段无效')
        hypothesis = _hypothesis(state, data['hypothesis_id'])
        require(hypothesis is not None, 'RESOURCE_NOT_FOUND', '假设卡不可访问')
        require(hypothesis['status'] == 'awaiting_review' and all(level in hypothesis['validations'] for level in ('small_race', 'live_attribution')), 'INVALID_TRANSITION', '完成读者比较与发布结果记录后才可总结经验')
        require(data['verdict'] in ('supported', 'refuted', 'inconclusive'), 'INVALID_INPUT', '裁决只能为支持、反证或不确定')
        if data['verdict'] == 'supported':
            require(all(hypothesis['validations'][level].get('meets_minimum_lift') is True for level in ('small_race', 'live_attribution')),
                    'INVALID_TRANSITION', 'A/B 两阶段都未达到预设提升门槛，不能裁决为支持')
        notes = validate_text(data['notes'], '裁决依据', 1000, True)
        hypothesis.update(verdict=data['verdict'], verdict_notes=notes, status='reviewed',
            ledger_status='proposed', reviewed_at=now(), evidence_grade='exploratory',
            limitation='小样本与人工回填的探索性记录；除非实验分流和数据质量足以支持，否则不作因果或稳定规律结论。')
        return

    require(set(data) == {'hypothesis_id', 'status'}, 'INVALID_INPUT', '经验状态字段无效')
    hypothesis = _hypothesis(state, data['hypothesis_id'])
    require(hypothesis is not None, 'RESOURCE_NOT_FOUND', '假设卡不可访问')
    if data['status'] == 'accepted':
        require(hypothesis['ledger_status'] == 'proposed', 'INVALID_TRANSITION', '只有待审经验可以接受')
        hypothesis['ledger_status'] = 'accepted'
    elif data['status'] == 'rejected':
        require(hypothesis['ledger_status'] == 'proposed', 'INVALID_TRANSITION', '只有待审经验可以拒绝')
        hypothesis['ledger_status'] = 'rejected'
    elif data['status'] == 'revoked':
        require(hypothesis['ledger_status'] == 'accepted', 'INVALID_TRANSITION', '只有已接受经验可以撤销')
        hypothesis['ledger_status'] = 'revoked'
    else:
        require(False, 'INVALID_INPUT', '经验状态无效')
    hypothesis['ledger_updated_at'] = now()


def operations_source_url(value):
    from backend.operations import url
    return url(value)


def _record_windtunnel(operations, db, owner, hypothesis, payload, now):
    require(set(payload) == {'run_id', 'notes'}, 'INVALID_INPUT', '风洞记录字段无效')
    run = operations.store._get(db, payload['run_id'], owner)
    require(run.workflow_type == 'windtunnel' and run.run_status == 'SUCCEEDED', 'INVALID_TRANSITION', '必须关联已结束的风洞预演')
    report_state = run.windtunnel
    require(report_state.get('account_id') == hypothesis['account_id'] and report_state.get('hypothesis_id') == hypothesis['id'], 'RESOURCE_NOT_FOUND', '风洞任务没有绑定此假设和账号')
    require(report_state.get('reports'), 'INVALID_TRANSITION', '风洞预演没有已保存报告')
    report = report_state['reports'][-1]
    require(report['draft_hash'] == report_state['drafts'][-1]['hash'], 'VERSION_CONFLICT', '风洞报告不是当前稿件版本的结果')
    notes = validate_text(payload['notes'], '风洞备注', 600, True)
    outcomes = {}
    for row in report['results']:
        outcomes[row['status']] = outcomes.get(row['status'], 0) + 1
    return dict(run_id=run.run_id, report_id=report['id'], batch_id=report['batch_id'],
        draft_hash=report['draft_hash'], condition_hash=report['condition_hash'], outcomes=outcomes,
        mode=report['mode'], evidence_class='simulation' if report['mode'] == 'simulation' else 'model_review',
        notes=notes, recorded_at=now())


def _record_race(operations, db, owner, hypothesis, payload, now, timestamp):
    required = {'allocation', 'unit', 'arms', 'window', 'observed_at', 'notes'}
    require(required <= set(payload) <= required | {'reader_feedback', 'reader_question'}, 'INVALID_INPUT', '读者比较字段无效')
    feedback = None
    if 'reader_feedback' in payload:
        require(payload['unit'] == 'readers' and payload['allocation'] == 'observational', 'INVALID_INPUT', '手工试读只记录读者反馈，不声称平台随机分流')
        question = validate_text(payload.get('reader_question'), '理解问题', 300)
        feedback = payload['reader_feedback']
        require(isinstance(feedback, list) and 2 <= len(feedback) <= 200, 'INVALID_INPUT', '请记录 2 至 200 位真实读者的反馈')
        aliases = set()
        normalized_feedback = []
        for row in feedback:
            require(isinstance(row, dict) and set(row) == {'reader_id', 'label', 'understood', 'would_act', 'answer'}, 'INVALID_INPUT', '读者反馈字段无效')
            alias = validate_text(row['reader_id'], '匿名读者编号', 60)
            require(alias not in aliases, 'DUPLICATE', '同一位读者只计一次，请让每位读者只看一个版本')
            aliases.add(alias)
            require(row['label'] in ('A', 'B') and type(row['understood']) is bool and type(row['would_act']) is bool, 'INVALID_INPUT', '请选择版本、是否看懂及是否愿意行动')
            answer = validate_text(row['answer'], '读者原话', 1000)
            normalized_feedback.append(dict(reader_id=alias, label=row['label'], understood=row['understood'], would_act=row['would_act'], answer=answer))
        feedback = normalized_feedback
    else:
        require('reader_question' not in payload, 'INVALID_INPUT', '理解问题需与真实读者反馈一起提交')
    require(payload['window'] == hypothesis['window'], 'INVALID_INPUT', '赛马观察窗口不能偏离假设卡预设窗口')
    allocation, unit = payload['allocation'], payload['unit']
    require(allocation in ('randomized', 'observational'), 'INVALID_INPUT', '分流方式无效')
    require(unit in ('readers', 'views', 'impressions', 'link_clicks'), 'INVALID_INPUT', '样本单位无效')
    require(unit == hypothesis['denominator'] or unit == 'readers', 'INVALID_INPUT', '赛马分母需与预设假设口径一致；读者测试仅作前期代理指标')
    arms = payload['arms']
    require(isinstance(arms, list) and len(arms) == 2, 'INVALID_INPUT', '首期赛马固定比较 A 基线与 B 变体')
    refs, normalized = set(), []
    for arm in arms:
        require(isinstance(arm, dict) and set(arm) == {'label', 'run_id', 'draft_ref', 'denominator', 'outcomes'}, 'INVALID_INPUT', '版本组字段无效')
        label = validate_text(arm['label'], '版本组名称', 60)
        ref = validate_text(arm['draft_ref'], '稿件版本', 100)
        identity = (arm['run_id'], ref)
        require(identity not in refs, 'DUPLICATE', '每个版本组必须使用不同的稿件版本')
        refs.add(identity)
        run = operations.store._get(db, arm['run_id'], owner)
        require(run.workflow_type == 'creation' and run.context.get('operations', {}).get('account_id') == hypothesis['account_id'], 'RESOURCE_NOT_FOUND', '稿件不属于此账号')
        require(any(d['ref'] == ref for d in run.drafts), 'RESOURCE_NOT_FOUND', '稿件版本不可访问')
        if feedback is not None:
            rows = [row for row in feedback if row['label'] == label]
            require(rows, 'INVALID_INPUT', 'A 和 B 都需要真实读者反馈')
            require(arm['denominator'] == len(rows) and arm['outcomes'] == sum(row['would_act'] for row in rows), 'INVALID_INPUT', '汇总数字必须与逐条读者反馈一致')
            require(run.context.get('mode') == 'live', 'INVALID_INPUT', '真实读者试读请选择真实创作稿件，不使用模拟稿')
        denominator = integer(arm['denominator'], '样本或曝光数', 1)
        outcomes = integer(arm['outcomes'], '目标行动数')
        require(outcomes <= denominator, 'INVALID_INPUT', '目标行动数不能大于样本或曝光数')
        normalized.append(dict(label=label, run_id=run.run_id, draft_ref=ref,
            content_hash=next(d['content_hash'] for d in run.drafts if d['ref'] == ref),
            content_mode=run.context.get('mode', 'unknown'), denominator=denominator,
            outcomes=outcomes, rate=round(outcomes/denominator, 6)))
    require({arm['label'] for arm in normalized} == {'A', 'B'}, 'INVALID_INPUT', '必须明确标记 A 基线与 B 变体')
    require(len({arm['content_mode'] for arm in normalized}) == 1, 'INVALID_INPUT', '同一场赛马不能混用模拟稿和真实模型稿')
    if feedback is not None:
        require(len({arm['content_hash'] for arm in normalized}) == 2, 'INVALID_INPUT', 'A 和 B 正文相同，请先选一份真正修改过的稿件')
    observed = timestamp(payload['observed_at'])
    notes = validate_text(payload['notes'], '试验备注', 800, True)
    control, variant = next(a for a in normalized if a['label']=='A'), next(a for a in normalized if a['label']=='B')
    lift = _relative_lift(control['rate'], variant['rate'])
    result = dict(allocation=allocation, unit=unit, arms=normalized, window=payload['window'], observed_at=observed, notes=notes,
        evidence_class='exploratory_randomized' if allocation == 'randomized' else 'observational',
        causal_claim='not_established', variant_lift_pct=lift,
        meets_minimum_lift=lift is not None and lift >= hypothesis['minimum_lift_pct'],
        interpretation='B 相对 A 的原始比例差异；未进行统计检验，不代表效果确定。')
    if feedback is not None:
        result.update(reader_question=question, reader_feedback=feedback, evidence_class='user_recorded_reader_feedback',
            proxy_metric='stated_intent',
            comprehension={label: dict(readers=sum(r['label'] == label for r in feedback), understood=sum(r['label'] == label and r['understood'] for r in feedback)) for label in ('A', 'B')},
            interpretation='逐条真实试读反馈：愿意行动不等于实际关注、下单或注册。发布前用于找出读者没看懂的地方。')
    return result


def _record_attribution(operations, db, owner, state, hypothesis, payload, now, timestamp):
    from backend.operations import item
    from backend.analytics import window_quality, parsed
    require(set(payload) == {'items', 'evidence_method', 'source_note', 'observed_at'}, 'INVALID_INPUT', '实盘归因字段无效')
    require(payload['evidence_method'] == 'manual_entry', 'INVALID_INPUT', '首期只支持人工回填；平台导出与追踪链接尚未接入核验')
    items = payload['items']
    require(isinstance(items, list) and 2 <= len(items) <= 8, 'INVALID_INPUT', '实盘归因需关联 2 至 8 个版本结果')
    race = hypothesis['validations'].get('small_race')
    require(race is not None, 'INVALID_TRANSITION', '请先完成小流量赛马记录')
    expected_refs = {(arm['run_id'], arm['draft_ref']) for arm in race['arms']}
    require(len({entry.get('publication_id') for entry in items if isinstance(entry, dict)}) == len(items), 'INVALID_INPUT', '实盘结果不可重复关联同一作品')
    result_refs, normalized = set(), []
    observed = timestamp(payload['observed_at'])
    for entry in items:
        require(isinstance(entry, dict) and set(entry) == {'publication_id', 'metric_id'}, 'INVALID_INPUT', '实盘作品与指标字段无效')
        publication = item(state['publications'], entry['publication_id'])
        require(publication['account_id'] == hypothesis['account_id'] and publication['platform'] == hypothesis['platform'], 'RESOURCE_NOT_FOUND', '发布记录不属于当前假设账号与平台')
        require(publication['status'] == 'MANUAL_REPORTED' and publication['mode'] == 'live' and publication['provenance'] != 'simulation' and publication.get('url'),
                'INVALID_TRANSITION', '实盘归因只接受已人工回填链接的真实发布记录')
        identity = (publication.get('run_id'), publication['draft_ref'])
        require(identity in expected_refs, 'INVALID_TRANSITION', '实盘作品版本不属于已登记的赛马组')
        race_arm = next(a for a in race['arms'] if (a['run_id'], a['draft_ref']) == identity)
        require(publication['content_hash'] == race_arm['content_hash'], 'VERSION_CONFLICT', '发布稿件与试读版本不一致，请重新比较实际发布版本')
        result_refs.add(identity)
        metric = item(state['metrics'], entry['metric_id'])
        require(metric['publication_id'] == publication['id'] and metric['source_type'] == 'manual', 'RESOURCE_NOT_FOUND', '指标不属于该真实作品')
        require(metric['window'] == hypothesis['window'], 'INVALID_INPUT', '实盘指标必须使用假设卡预设观察窗口')
        latest = [m for m in state['metrics'] if m['publication_id'] == publication['id'] and m['window'] == metric['window']][-1]
        require(latest['id'] == metric['id'], 'VERSION_CONFLICT', '只能使用最新指标快照')
        require(publication.get('published_at'), 'INVALID_INPUT', '请先补全作品的实际发布时间')
        quality, hours = window_quality(publication, metric)
        require(quality == 'comparable', 'INVALID_INPUT', f"{race_arm['label']} 版实际记录在发布后 {hours} 小时，不在 {hypothesis['window']} 的可比较范围内；请选同一观察时长的数据")
        require(parsed(metric['observed_at']) <= parsed(observed), 'INVALID_INPUT', '结果记录时间不能早于所选数据的采集时间')
        values = metric['values']
        outcome = values.get(hypothesis['metric'])
        denominator = values.get(hypothesis['denominator'])
        require(outcome is not None and denominator is not None and denominator > 0, 'INVALID_INPUT', '真实归因缺少主要目标指标或曝光/播放分母')
        require(outcome <= denominator, 'INVALID_INPUT', '目标转化数不能大于曝光/播放分母')
        normalized.append(dict(publication_id=publication['id'], run_id=publication['run_id'], label=race_arm['label'], draft_ref=publication['draft_ref'],
            content_hash=publication['content_hash'], metric_id=metric['id'], window=metric['window'],
            observed_at=metric['observed_at'], elapsed_hours=hours, denominator=denominator, outcome=outcome,
            rate=round(outcome/denominator, 6), evidence_source='user_recorded_metrics'))
    require(result_refs == expected_refs, 'INVALID_INPUT', '需为赛马中的每个内容版本提供真实发布和指标记录')
    # Multiple publications of either fixed version contribute to that arm.
    aggregates = {}
    for label in ('A', 'B'):
        group = [x for x in normalized if x['label'] == label]
        denominator = sum(x['denominator'] for x in group)
        outcome = sum(x['outcome'] for x in group)
        aggregates[label] = dict(publications=len(group), denominator=denominator, outcome=outcome, rate=outcome / denominator)
    control, variant = aggregates['A'], aggregates['B']
    lift = _relative_lift(control['rate'], variant['rate'])
    source_note = validate_text(payload['source_note'], '数据来源说明', 600)
    return dict(items=normalized, aggregates=aggregates, evidence_method=payload['evidence_method'], source_note=source_note,
        observed_at=observed, recorded_at=now(), evidence_class='user_provided_real_publication_data',
        variant_lift_pct=lift, meets_minimum_lift=lift is not None and lift >= hypothesis['minimum_lift_pct'],
        causal_claim='not_established', interpretation='与具体发布版本关联的用户提供数据；平台未授权核验或随机设计不足时只作描述性归因。')


def _relative_lift(control_rate, variant_rate):
    if control_rate <= 0:
        return None
    return round((variant_rate / control_rate - 1) * 100, 2)
