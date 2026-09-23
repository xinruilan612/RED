"""Additive v0.5 account context for the four-role creation subprocess."""
import copy


def history_sample(context):
    op = context.get('operations', {})
    ids = {p['id'] for p in op.get('history', [])}
    return len({m['publication_id'] for m in op.get('metrics', [])
                if m['publication_id'] in ids and m['values'].get('views')})


def enrich(stage, value, context):
    if not isinstance(value, dict): return value
    result = copy.deepcopy(value)
    op = context.get('operations', {}); account = op.get('profile') or {}
    profile = account.get('profile', {})
    identity = {'account_id': op.get('account_id'), 'profile_revision': account.get('revision')}
    if stage == 'audience':
        count = history_sample(context)
        result.update(sample_size=count, status='partial' if count else 'needs_data', confidence='low',
            account_context=identity, history_refs=[p['id'] for p in op.get('history', [])],
            competitor_observations=op.get('competitors', []),
            evidence_limit='历史仅为描述性记录；偏好与传播效果分开，竞品观察未经独立核验。')
    if stage == 'research':
        trend = op.get('trend')
        result['topic_card'] = dict(topic=context['topic'], audience=profile.get('audience') or context['audience'],
            why_now=trend['angle'] if trend else '自主选题，暂无可核验的时效依据',
            evidence=[{'url': trend['source_url'], 'observed_at': trend['observed_at'], 'source_type':trend['source_type']}] if trend else [],
            account_fit=profile.get('positioning') or '账号定位尚待补充',
            risk=result.get('prohibited_claims', []),
            content_angles=[trend['angle']] if trend else ['结合真实场景解释问题', '整理可验证的尝试步骤'],
            limitation='选题卡基于用户线索；没有自动抓取、热度统计或时效核实。')
    if stage == 'strategy':
        experiment = op.get('experiment')
        result['content_brief'] = dict(**identity, goal=profile.get('goal') or '先验证内容是否对目标受众有用',
            core_viewpoint=result['angle'], audience=result['reader'],
            content_type='口播与分镜脚本' if op.get('format', 'video' if op.get('platform') == 'douyin' else 'image_text') == 'video' else '图文笔记',
            hook_options=result.get('candidate_angles', ['场景问题开头', '具体清单开头']),
            evidence_scope='引用用户素材与检索原文；历史表现与竞品观察不能证明正文事实',
            cta=result.get('cta', '邀请读者分享自己的场景'), banned=profile.get('banned', ''),
            publishing_window='由用户安排；暂无经过验证的最佳发布时间',
            recommendation_reason=result.get('why_account') or profile.get('positioning') or '来自本次需求，账号定位尚待补充')
        result['learning_refs'] = [m['id'] for m in op.get('memories', [])] + ([experiment['id']] if experiment else [])
        result['next_experiments'] = [m['text'] for m in op.get('memories', [])] + ([experiment['hypothesis']] if experiment else [])
    if stage == 'review':
        result['account_context'] = identity
        result['ranking_limit'] = '版本比较是内容评价；重要事实问题先阻断，不输出爆款概率。'
    return result
