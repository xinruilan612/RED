"""Parse explicitly collected creator DOM observations without network or browser I/O.

Collectors must identify each note stat from a verified icon signature. Positional
columns are deliberately not accepted. Display abbreviations are never estimates.
"""
import re
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo


ACCOUNT_LABELS = {
    '曝光数': 'exposure', '观看数': 'views',
    '封面点击率': 'cover_ctr', '视频完播率': 'video_completion_rate',
    '点赞数': 'likes', '评论数': 'comments', '收藏数': 'favorites', '分享数': 'shares',
}
IGNORED_ACCOUNT_LABELS = {'净涨粉','新增关注','取消关注','主页访客'}
PUBLIC_VISIBILITY_SOURCE = 'creator_note_card_no_private_label'
ACCOUNT_METRICS = tuple(dict.fromkeys(ACCOUNT_LABELS.values()))
RATE_METRICS = ('cover_ctr', 'video_completion_rate')
NOTE_METRICS = ('views', 'comments', 'likes', 'favorites', 'shares')


class CreatorMetricsError(ValueError):
    """A DOM or identity change prevents a trustworthy observation."""


def _check(condition, message):
    if not condition:
        raise CreatorMetricsError(message)


def _display(value, unit=''):
    _check(isinstance(value, str) and isinstance(unit, str), 'metric display must be text')
    _check(len(value) <= 100 and len(unit) <= 20, 'metric display too long')
    return value.strip() + unit.strip()


def exact_metric(value, *, percentage=False, signed=False):
    """Return exact counts or percentage points; signed is only for net followers."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if percentage:
        if not re.fullmatch(r'(?:0|[1-9][0-9]*)(?:\.[0-9]+)?%', text):
            return None
        number = float(text[:-1])
        return number if 0 <= number <= 100 else None
    negative = signed and text.startswith('-')
    count_text = text[1:] if negative else text
    if not re.fullmatch(r'(?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)', count_text):
        return None
    number = int(text.replace(',', ''))
    return number if abs(number) <= 10**12 else None


def _period(display, days, today):
    _check(isinstance(display, str), 'period display missing')
    _check(type(days) is int and 1 <= days <= 366, 'period days invalid')
    match = re.fullmatch(r'\s*统计周期\s*(\d{2})-(\d{2})\s*至\s*(\d{2})-(\d{2})\s*', display)
    _check(match is not None, 'period display changed')
    sm, sd, em, ed = map(int, match.groups())
    end_year = today.year - (1 if today.month == 1 and em == 12 else 0)
    start_year = end_year - (1 if (sm, sd) > (em, ed) else 0)
    try:
        start, end = date(start_year, sm, sd), date(end_year, em, ed)
    except ValueError as exc:
        raise CreatorMetricsError('period date invalid') from exc
    _check(end <= today, 'period ends in the future')
    _check((end - start).days + 1 == days, 'period days inconsistent')
    return start.isoformat(), end.isoformat()


def parse_creator_metrics(payload, *, source_id, creator_account_id, observed_at, today=None):
    """Validate a normalized collector packet against the bound source identity.

    ``today`` is an optional Shanghai calendar date for deterministic tests.
    Metrics use percentage points (``12.3%`` -> ``12.3``), never a 0..1 ratio.
    """
    _check(isinstance(payload, dict), 'collector payload invalid')
    _check(isinstance(source_id, str) and re.fullmatch(r'[0-9a-f]{24}', source_id), 'bound source invalid')
    _check(isinstance(creator_account_id, str) and re.fullmatch(r'[0-9]{1,30}', creator_account_id), 'bound creator account invalid')
    _check(payload.get('source_id') == source_id and payload.get('creator_account_id') == creator_account_id, 'bound identity mismatch')
    try:
        observed = datetime.fromisoformat(observed_at.replace('Z', '+00:00'))
    except (ValueError, AttributeError, TypeError) as exc:
        raise CreatorMetricsError('observation timestamp invalid') from exc
    _check(observed.tzinfo is not None, 'observation timezone missing')
    today = today or datetime.now(ZoneInfo('Asia/Shanghai')).date()
    _check(type(today) is date, 'today must be a calendar date')
    _check(observed.astimezone(ZoneInfo('Asia/Shanghai')).date() <= today, 'observation date in future')
    home = payload.get('home')
    _check(isinstance(home, dict), 'home DOM missing')
    label = home.get('account_label')
    identity = re.fullmatch(r'\s*小红书账号\s*[:：]\s*([0-9]+)\s*', label) if isinstance(label, str) else None
    _check(identity is not None and identity.group(1) == creator_account_id, 'creator home identity mismatch')
    start, end = _period(home.get('period'), home.get('period_days'), today)
    blocks = home.get('blocks')
    _check(isinstance(blocks, list) and 1 <= len(blocks) <= 30, 'home blocks invalid')
    metrics = dict.fromkeys(ACCOUNT_METRICS)
    displays, seen = {}, set()
    for block in blocks:
        _check(isinstance(block, dict), 'home block invalid')
        label = block.get('label')
        _check(isinstance(label, str), 'home metric label invalid')
        if label in IGNORED_ACCOUNT_LABELS:
            continue
        key = ACCOUNT_LABELS.get(label)
        _check(key is not None and key not in seen, 'unknown or duplicate home metric')
        seen.add(key)
        display = _display(block.get('value'), block.get('unit', ''))
        displays[key] = display
        metrics[key] = exact_metric(display, percentage=key in RATE_METRICS, signed=key == 'followers_gained')
    cards = payload.get('notes')
    _check(isinstance(cards, list) and len(cards) <= 100, 'note cards invalid')
    notes, seen = [], set()
    for card in cards:
        _check(isinstance(card, dict), 'note card invalid')
        if card.get('visibility') != 'public' or card.get('visibility_source') != PUBLIC_VISIBILITY_SOURCE:
            continue
        identity = card.get('id')
        _check(isinstance(identity, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,200}', identity) and identity not in seen, 'note identity invalid or duplicate')
        seen.add(identity)
        title, published = card.get('title'), card.get('time')
        _check(isinstance(title, str) and len(title) <= 500, 'note title invalid')
        _check(isinstance(published, str) and len(published) <= 100, 'note publication display invalid')
        stats = card.get('stats')
        _check(isinstance(stats, list) and len(stats) == len(NOTE_METRICS), 'note metric columns changed')
        values, raw = {'exposure': None}, {}
        for stat in stats:
            _check(isinstance(stat, dict), 'note stat invalid')
            key = stat.get('kind')
            _check(key in NOTE_METRICS and key not in raw, 'unknown or duplicate note icon kind')
            display = _display(stat.get('value'))
            raw[key] = display
            values[key] = exact_metric(display)
        notes.append({'id': identity, 'title': title, 'published_display': published,
                      'visibility':'public','visibility_source':PUBLIC_VISIBILITY_SOURCE,
                      'metrics': values, 'metric_displays': raw,
                      'source_url': 'https://www.xiaohongshu.com/explore/' + identity})
    return {'status': 'synced', 'source_id': source_id, 'creator_account_id': creator_account_id,
            'observed_at': observed.astimezone(timezone.utc).isoformat(), 'source_updated_at': None,
            'source_method': 'creator_browser_dom', 'official_api': False,
            'account': {'period_start': start, 'period_end': end, 'period_days': home['period_days'],
                        'period_display': home['period'], 'metrics': metrics, 'metric_displays': displays},
            'notes': notes, 'error': None}
