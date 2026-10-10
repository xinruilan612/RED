"""Read only the already-open creator home and note-manager surfaces.

Run --bind-account once as the local administrator, using the creator account
number visibly verified by the user. No remote browser attachment, stealth,
private API calls, permission application, publication or comment writing.
"""
import argparse
import asyncio
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
HOME = 'https://creator.xiaohongshu.com/new/home'
NOTES = 'https://creator.xiaohongshu.com/new/note-manager'
PROFILE = 'https://www.xiaohongshu.com/explore'

# Signatures are the five rendered SVG icons verified on the note-manager UI.
# Unknown icons fail closed; positional number lists alone are not accepted.
ICON_PREFIXES = {
    'views': 'M7.99902 3.83398',
    'comments': 'M3.18233 10.985',
    'likes': 'M3.25611 3.91336',
    'favorites': 'M10.8848 14.2322',
    'shares': 'M8.28672 5.15797',
}

# Filter private cards before extracting any identifier, title, or metric.
NOTE_CARDS_EXTRACT = """els => els.slice(0,30)
 .filter(e => !e.innerText.includes('仅自己可见'))
 .map(e=>({
   id:JSON.parse(e.getAttribute('data-impression')||'{}')?.noteTarget?.value?.noteId,
   visibility:'public',visibility_source:'creator_note_card_no_private_label',
   title:e.querySelector('.note-card__title')?.innerText || '',
   time:e.querySelector('.note-card__time')?.innerText || '',
   stats:Array.from(e.querySelectorAll('.note-card__stat')).map(s=>({
     icon:s.querySelector('svg path')?.getAttribute('d') || '',value:s.querySelector('span')?.innerText || ''
   }))
 }))"""


class ReaderStopped(Exception):
    pass


def private_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_suffix('.tmp')
    with os.fdopen(os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w') as f:
        json.dump(value, f, ensure_ascii=False)
    os.replace(temp, path)
    os.chmod(path, 0o600)


def bootstrap_cookies(path):
    """Existing explicitly bound connector session, filtered to this platform."""
    raw = json.loads(path.read_text())
    if isinstance(raw, dict):
        raw = raw.get('cookies')
    if not isinstance(raw, list):
        raise ReaderStopped('CREATOR_SESSION_INVALID')
    result = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        domain = str(item.get('domain', ''))
        if domain.lstrip('.') not in ('xiaohongshu.com', 'www.xiaohongshu.com', 'creator.xiaohongshu.com'):
            continue
        if not isinstance(item.get('name'), str) or not isinstance(item.get('value'), str):
            continue
        cookie = {k: item[k] for k in ('name', 'value', 'domain', 'path', 'httpOnly', 'secure') if k in item}
        cookie.setdefault('path', '/')
        expiry = item.get('expires')
        if isinstance(expiry, (int, float)) and expiry > 0:
            cookie['expires'] = expiry
        same = str(item.get('sameSite', '')).capitalize()
        if same in ('Strict', 'Lax', 'None'):
            cookie['sameSite'] = same
        result.append(cookie)
    if not result:
        raise ReaderStopped('CREATOR_SESSION_INVALID')
    return result


async def check_page(page):
    text = await page.locator('body').inner_text(timeout=5000)
    if any(v in text for v in ('请通过验证', '访问频繁', '访问异常', '完成安全验证')):
        raise ReaderStopped('CREATOR_SOURCE_LIMITED')
    if not page.url.startswith(('https://creator.xiaohongshu.com/', 'https://www.xiaohongshu.com/')):
        raise ReaderStopped('CREATOR_UNEXPECTED_REDIRECT')
    return text


async def verify_public_identity(page, expected):
    await page.goto(PROFILE, wait_until='domcontentloaded', timeout=35000)
    await check_page(page)
    me = page.locator("a[href*='/user/profile/']").filter(has=page.get_by_text('我', exact=True))
    try:
        await me.first.wait_for(state='visible', timeout=12000)
    except Exception:
        raise ReaderStopped('CREATOR_LOGIN_REQUIRED') from None
    href = await me.first.get_attribute('href')
    match = re.search(r'/user/profile/([0-9a-f]{24})(?:[/?#]|$)', href or '')
    if not match or match[1] != expected:
        raise ReaderStopped('CREATOR_IDENTITY_CHANGED')


async def home_data(page, account, login=False, folder=None):
    await page.goto(HOME, wait_until='domcontentloaded', timeout=35000)
    if login:
        # A manual scan refreshes this dedicated local session, never grants new scope.
        print('CREATOR_LOGIN_WINDOW: complete login in the dedicated Chromium window.', file=sys.stderr, flush=True)
        for _ in range(180):
            text = await check_page(page)
            if '小红书账号' in text and await page.locator('.time-scope').count():
                break
            await asyncio.sleep(2)
    try:
        await page.locator('.time-scope').wait_for(state='visible', timeout=12000)
    except Exception:
        raise ReaderStopped('CREATOR_LOGIN_REQUIRED') from None
    text = await check_page(page)
    match = re.search(r'小红书账号\s*[:：]\s*([0-9A-Za-z_-]+)', text)
    if not match or match[1] != account:
        raise ReaderStopped('CREATOR_IDENTITY_CHANGED')
    # Observe the default tab instead of switching it and racing an asynchronous
    # period request. A changed default is an explicit unsupported observation.
    if await page.locator('.d-segment-item.active').inner_text(timeout=5000) != '近7日':
        raise ReaderStopped('CREATOR_PERIOD_CHANGED')
    await page.locator('.creator-block .number').first.wait_for(state='visible', timeout=10000)
    extract = """() => ({
      account_label: document.body.innerText.match(/小红书账号\\s*[:：]\\s*[0-9A-Za-z_-]+/)[0],
      period: document.querySelector('.time-scope').innerText, period_days: 7,
      blocks: Array.from(document.querySelectorAll('.creator-block'))
       .filter(e=>!['净涨粉','新增关注','取消关注','主页访客'].includes(e.querySelector('.title')?.innerText || ''))
       .map(e=>({
        label:e.querySelector('.title')?.innerText || '',
        value:e.querySelector('.number')?.innerText || '',
        unit:e.querySelector('.number-container')?.innerText.includes('%') ? '%' : ''
      }))
    })"""
    previous = await page.evaluate(extract)
    for _ in range(5):
        await asyncio.sleep(0.4)
        current = await page.evaluate(extract)
        if current == previous:
            return current
        previous = current
    raise ReaderStopped('CREATOR_DATA_UNSTABLE')


async def read_pages(args, folder, binding):
    from playwright.async_api import async_playwright
    from backend.creator_metrics import parse_creator_metrics
    async with async_playwright() as pw:
        context = await pw.chromium.launch_persistent_context(
            str(folder / 'browser-profile'), headless=not args.login,
            viewport={'width': 1280, 'height': 900})
        try:
            cookie_file = ROOT / 'runtime/xhs-local/session/cookies.json'
            fingerprint = hashlib.sha256(cookie_file.read_bytes()).hexdigest()
            bootstrap = folder / 'bootstrap.json'
            previous = json.loads(bootstrap.read_text()) if bootstrap.exists() else {}
            if previous.get('fingerprint') != fingerprint:
                await context.add_cookies(bootstrap_cookies(cookie_file))
                private_json(bootstrap, {'fingerprint': fingerprint})
            page = await context.new_page()
            if not args.login:
                await verify_public_identity(page, args.source_id)
            home = await home_data(page, binding['creator_account_id'], args.login, folder)
            notes_error = None
            cards = []
            try:
                await page.goto(NOTES, wait_until='domcontentloaded', timeout=35000)
                await check_page(page)
                await page.locator('.note-card').first.wait_for(state='visible', timeout=12000)
                cards = await page.locator('.note-card').evaluate_all(NOTE_CARDS_EXTRACT)
            except ReaderStopped:
                raise
            except Exception:
                # Preserve a verified home observation on a notes-only failure.
                # Unverified empty lists are not evidence that all notes vanished.
                text = await check_page(page)
                if not re.search(r'(?:^|\n)全部\s*0(?:\n|$)', text):
                    notes_error = 'CREATOR_NOTES_UNAVAILABLE'
            for card in cards:
                for stat in card['stats']:
                    icon = stat.pop('icon', '')
                    stat['kind'] = next((key for key, prefix in ICON_PREFIXES.items() if icon.startswith(prefix)), None)
            # Independently re-check both visible account identities after collecting.
            await home_data(page, binding['creator_account_id'])
            await verify_public_identity(page, args.source_id)
            observed = datetime.now(timezone.utc).isoformat()
            result = parse_creator_metrics({'source_id': args.source_id,
                'creator_account_id': binding['creator_account_id'], 'home': home, 'notes': cards},
                source_id=args.source_id, creator_account_id=binding['creator_account_id'], observed_at=observed)
            if notes_error:
                result.update(status='partial', error=notes_error)
            result['coverage'] = '笔记管理首屏已加载最多30篇中已核对的公开笔记；仅自己可见条目不采集，不代表全部历史'
            return result
        finally:
            await context.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-id', required=True)
    parser.add_argument('--bind-account')
    parser.add_argument('--login', action='store_true')
    args = parser.parse_args()
    if not re.fullmatch(r'[0-9a-f]{24}', args.source_id):
        parser.error('invalid source id')
    os.umask(0o077)
    folder = ROOT / 'runtime/xhs-local/creator' / args.source_id
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    binding_file = folder / 'binding.json'
    if args.bind_account:
        if not re.fullmatch(r'[0-9A-Za-z_-]{1,40}', args.bind_account):
            parser.error('invalid creator account')
        if binding_file.exists() and json.loads(binding_file.read_text()) != {'source_id': args.source_id, 'creator_account_id': args.bind_account}:
            parser.error('binding is immutable; use a separately reviewed migration')
        private_json(binding_file, {'source_id': args.source_id, 'creator_account_id': args.bind_account})
    result = {'status': 'failed', 'source_id': args.source_id, 'source_method': 'creator_browser_dom',
              'observed_at': datetime.now(timezone.utc).isoformat(), 'source_updated_at': None,
              'account': None, 'notes': [], 'error': 'CREATOR_READER_FAILED'}
    try:
        binding = json.loads(binding_file.read_text())
        if binding['source_id'] != args.source_id:
            raise ReaderStopped('CREATOR_IDENTITY_CHANGED')
        with open(folder / 'reader.lock', 'w') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ReaderStopped('CREATOR_BUSY') from None
            result = asyncio.run(read_pages(args, folder, binding))
    except ReaderStopped as exc:
        result['error'] = str(exc)
    except Exception:
        # Do not leak browser URLs, cookies, page contents or traceback into logs.
        pass
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
