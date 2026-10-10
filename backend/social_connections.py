"""Truthful, owner-scoped data-centre projection; no platform session or scraper.

External connection support requires a reviewed adapter in a later migration.
An account profile, manually entered metric, or OAuth identity is not a data grant.
"""
from copy import deepcopy
from datetime import datetime

from backend.accounts import find_account
from backend.contracts import require


VERIFIED_ON = '2026-10-10'
SOURCES = (
    dict(id='creator_terms', title='小红书创作服务平台用户协议',
         url='https://agree.xiaohongshu.com/h5/terms/ZXXY20260422001/-1',
         reviewed_on=VERIFIED_ON, method='official_page_browser',
         finding='4.2、4.4 限制数据使用；5.2 限制未经授权的第三方工具和自动访问。'),
    dict(id='account_scopes', title='小红书账号授权范围',
         url='https://openaccount.xiaohongshu.com/docs/scope',
         reviewed_on=VERIFIED_ON, method='official_page_browser',
         finding='当前仅 basic_info 开放，读取笔记等权限仍在规划中。'),
    dict(id='account_webhooks', title='小红书账号 Webhook',
         url='https://openaccount.xiaohongshu.com/docs/webhook',
         reviewed_on=VERIFIED_ON, method='official_page',
         finding='授权撤销与扫码确认事件不提供评论或自然笔记流量推送。'),
)
FIELDS = (
    ('views', '观看量（沿用现有记录口径）', 'count'),
    ('likes', '点赞数', 'count'),
    ('saves', '收藏数', 'count'),
    ('comments', '评论数', 'count'),
    ('shares', '分享数', 'count'),
)
ADMISSION_REQUIREMENTS = (
    '平台或获授权服务商出具适用本项目的数据访问依据，不能以开源许可证代替。',
    '明确个人账号、自然笔记曝光/观看、评论正文的覆盖范围；广告指标不能替代自然指标。',
    '明确保存期限、本机/云端处理、第三方模型处理、RAG 与再利用许可。',
    '完成服务端适配器、用户隔离、撤销、限流和恢复测试，登记实测字段与更新延迟。',
    '管理员审核材料后部署已审查适配器；前端或账号资料中的标记不能启用同步。',
)


def capabilities(platform='xiaohongshu'):
    require(platform in ('xiaohongshu', 'douyin'), 'INVALID_INPUT', '平台无效')
    xhs = platform == 'xiaohongshu'
    return dict(platform=platform, checked_on=VERIFIED_ON if xhs else None,
                goal='连接后自动同步账号数据，并显示源数据与本项目的更新时间',
                implemented_adapter=None, connection_available=False,
                automatic_sync_available=False, realtime_verified=False,
                status='permission_required' if xhs else 'not_implemented',
                reason=('尚无适用于个人账号自然笔记与评论的已授权且实测通过的数据通道。'
                        if xhs else '尚未实施抖音数据连接器。'),
                features={name: dict(available=False, status='not_connected') for name in
                          ('identity', 'natural_metrics', 'comment_content', 'note_search')},
                fields=[dict(key=key, label=label, unit=unit, automatic_available=False)
                        for key, label, unit in FIELDS],
                sources=deepcopy(list(SOURCES)) if xhs else [],
                admission_requirements=list(ADMISSION_REQUIREMENTS),
                local_recording=dict(available=True, method='manual',
                                    official_export_parser_available=False,
                                    limitation='现有作品归档与指标录入是用户记录，未核实平台；不提供自动抓取。'))


def _time(value):
    """Compare timezone-aware instants, not offset-bearing ISO strings."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed if parsed.tzinfo is not None else None
    except ValueError:
        return None


def data_center(state, identity):
    """Read an already owner-scoped Operations state, never accept client state.

    Counts describe local records only. We deliberately never total metric
    snapshots: different windows and revisions would double count engagement.
    """
    account = find_account(state, identity)
    result = capabilities(account['platform'])
    posts = [p for p in state.get('publications', [])
             if p.get('account_id') == identity and p.get('platform') == account['platform']
             and p.get('provenance') == 'manual']
    post_ids = {p['id'] for p in posts}
    metrics = [m for m in state.get('metrics', [])
               if m.get('account_id') == identity and m.get('platform') == account['platform']
               and m.get('publication_id') in post_ids and m.get('source_type') == 'manual']
    dated = [(m, _time(m.get('observed_at'))) for m in metrics]
    dated = [(m, t) for m, t in dated if t is not None]
    latest = max(dated, key=lambda pair: pair[1])[0] if dated else None
    # Explicit allowlist prevents a legacy/custom record carrying credentials
    # or unrelated account metadata from escaping into this read endpoint.
    latest_post = next((p for p in posts if latest and p['id'] == latest['publication_id']), None)
    snapshot = None if latest is None else dict(
        metric_id=latest['id'], publication_id=latest['publication_id'],
        observed_at=latest['observed_at'], window=latest.get('window'),
        source_type='manual', verified=False,
        publication_title=(latest_post.get('content') or {}).get('selected_title'),
        publication_url=latest_post.get('url'),
        values={key: latest.get('values', {}).get(key) for key, _, _ in FIELDS})
    result.update(account_id=identity, account_name=account['name'],
                  connection_status='not_connected', last_sync_at=None,
                  source_updated_at=None, next_sync_at=None,
                  local_records=dict(publication_count=len(posts),
                                     metric_snapshot_count=len(metrics),
                                     latest_metric=snapshot,
                                     comment_content_count=None,
                                     limitation='数量是本项目内的人工记录；评论数不代表已获取评论正文。'))
    return result


class SocialConnections:
    """Owner boundary is inherited from Operations.read, not browser input."""
    def __init__(self, operations):
        self.operations = operations

    def read(self, owner, account_id):
        return data_center(self.operations.read(owner), account_id)

    def catalog(self, platform='xiaohongshu'):
        return capabilities(platform)
