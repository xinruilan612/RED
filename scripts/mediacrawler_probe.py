"""Local, explicitly requested non-commercial probe; no publishing or model calls."""
import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import sys
from types import MethodType
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / 'runtime/mediacrawler'
REVISION = 'e9dd17a16338c3915f2335bc609383d316e055f2'
OUT = ROOT / 'runtime/mediacrawler-probe'
MAX_NOTES, MAX_COMMENTS, MAX_REQUESTS = 3, 20, 12

class ProbeStopped(Exception):
    pass


class ReadBudget:
    def __init__(self, raw_request, report, delay=5):
        self.raw_request,self.report,self.delay=raw_request,report,delay
        self.stopped=False

    async def send(self, client, method, url, **kwargs):
        if self.stopped or self.report['requests']>=MAX_REQUESTS:
            raise ProbeStopped('REQUEST_LIMIT_OR_STOP')
        self.report['requests']+=1
        await asyncio.sleep(self.delay)
        try:
            return await self.raw_request(client,method,url,**kwargs)
        except Exception as exc:
            self.stopped=True
            raise ProbeStopped('SOURCE_STOPPED_'+type(exc).__name__) from None


def profile_id(url):
    p = urlsplit(url)
    match = re.fullmatch(r'/user/profile/([a-f0-9]{24})/?', p.path)
    if p.scheme != 'https' or p.hostname != 'www.xiaohongshu.com' or p.username or not match:
        raise ValueError('Expected the resolved Xiaohongshu profile URL')
    return match[1]


def clean_note(raw, owner):
    if raw.get('user', {}).get('user_id') != owner:
        raise ProbeStopped('NOTE_OWNER_MISMATCH')
    return {**{k:raw.get(k) for k in ('note_id','type','title','desc','time','last_update_time')},
            'metrics':{k:raw.get('interact_info',{}).get(k) for k in ('liked_count','collected_count','comment_count','share_count')},
            'views':None,'impressions':None,'source':'public_note','verified_owner':True}


def clean_comments(items):
    seen, result = set(), []
    for item in items:
        identity = item.get('id')
        if not identity or identity in seen:
            continue
        seen.add(identity)
        result.append({k:item.get(k) for k in ('id','content','create_time','like_count')})
        if len(result) == MAX_COMMENTS:
            break
    return result


def private_json(path, value):
    fd = os.open(path, os.O_WRONLY|os.O_CREAT|os.O_TRUNC, 0o600)
    with os.fdopen(fd,'w') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2)


async def run(url):
    owner = profile_id(url)
    OUT.mkdir(parents=True,exist_ok=True,mode=0o700)
    os.umask(0o077)
    os.chdir(UPSTREAM)
    sys.path.insert(0,str(UPSTREAM))
    import config
    for key,value in {'ENABLE_CDP_MODE':False,'CDP_CONNECT_EXISTING':False,'ENABLE_IP_PROXY':False,
        'SAVE_LOGIN_STATE':False,'HEADLESS':False,'XHS_INTERNATIONAL':False,'MAX_CONCURRENCY_NUM':1,
        'ENABLE_GET_MEDIA':False,'ENABLE_GET_SUB_COMMENTS':False,'ENABLE_GET_WORDCLOUD':False,
        'CRAWLER_MAX_NOTES_COUNT':MAX_NOTES,'CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES':MAX_COMMENTS,
        'CRAWLER_MAX_SLEEP_SEC':5,'COOKIES':''}.items():
        setattr(config,key,value)
    from playwright.async_api import async_playwright
    from media_platform.xhs.core import XiaoHongShuCrawler
    from media_platform.xhs.client import XiaoHongShuClient
    from media_platform.xhs.help import parse_creator_info_from_url
    logging.disable(logging.CRITICAL)
    report={'status':'waiting_login','notes':[],'comment_count':0,'requests':0,
            'scope':{'max_notes':MAX_NOTES,'max_comments_per_note':MAX_COMMENTS},
            'automatic_sync':False,'views':None,'impressions':None}
    def save(): private_json(OUT/'result.json',report)
    save()
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        context = await browser.new_context(viewport={'width':1200,'height':850})
        page = await context.new_page()
        try:
            await page.goto(url,wait_until='domcontentloaded',timeout=45000)
            print('WAITING_LOGIN: scan the login QR in the separate Chromium window.',flush=True)
            captured = False
            for _ in range(180):
                if '请通过验证' in await page.content():
                    raise ProbeStopped('CAPTCHA_REQUIRES_USER')
                me = page.locator("a[href*='/user/profile/']").filter(has=page.get_by_text('我',exact=True))
                if await me.count() and await me.first.is_visible():
                    logged_url=await me.first.get_attribute('href')
                    if owner not in (logged_url or ''):
                        raise ProbeStopped('LOGIN_ACCOUNT_MISMATCH')
                    break
                qr=page.locator('img.qrcode-img')
                if not captured and await qr.count() and await qr.first.is_visible():
                    await qr.first.screenshot(path=str(OUT/'login-qr.png'))
                    captured=True
                    print('QR_READY',flush=True)
                await asyncio.sleep(2)
            else:
                raise ProbeStopped('LOGIN_TIMEOUT')
            print('LOGIN_CONFIRMED: beginning bounded read-only probe.',flush=True)
            crawler = XiaoHongShuCrawler()
            crawler.browser_context,crawler.context_page=context,page
            client = await crawler.create_xhs_client(None)
            raw_request=XiaoHongShuClient.request.__wrapped__
            budget=ReadBudget(raw_request,report)
            client.request=MethodType(budget.send,client)
            scope=parse_creator_info_from_url(url)
            report['status']='running';save()
            # One list page only. The server may return more metadata; only 3 are processed.
            listing=await client.get_notes_by_creator(owner,'',page_size=MAX_NOTES,
                          xsec_token=scope.xsec_token,xsec_source=scope.xsec_source)
            for item in listing.get('notes',[])[:MAX_NOTES]:
                raw=await client.get_note_by_id(item['note_id'],item.get('xsec_source') or 'pc_user',item.get('xsec_token',''))
                if not raw:
                    raise ProbeStopped('NOTE_BODY_MISSING')
                note=clean_note(raw,owner)
                comments=await client.get_note_all_comments(item['note_id'],item.get('xsec_token',''),
                                                          crawl_interval=5,max_count=MAX_COMMENTS)
                note['comments']=clean_comments(comments)
                report['notes'].append(note)
                report['comment_count']+=len(note['comments'])
                save()
            report['status']='done' if report['notes'] else 'empty';save()
            print('PROBE_FINISHED: notes='+str(len(report['notes']))+' comments='+str(report['comment_count']),flush=True)
        except ProbeStopped as exc:
            report['status']='stopped';report['reason']=str(exc);save()
            print('PROBE_STOPPED: '+str(exc),flush=True)
            # No retry, alternate account, proxy or automatic verification.
        except Exception as exc:
            report['status']='failed';report['reason']=type(exc).__name__;save()
            print('PROBE_FAILED: '+type(exc).__name__,flush=True)
        finally:
            await context.close();await browser.close()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--profile-file',type=Path);parser.add_argument('--check',action='store_true');args=parser.parse_args()
    revision=subprocess.check_output(['git','-C',str(UPSTREAM),'rev-parse','HEAD'],text=True).strip()
    if revision!=REVISION:
        raise SystemExit('Upstream revision changed; review before executing.')
    if args.check:
        import playwright, xhshow
        print('Pinned MediaCrawler and isolated dependencies available. No browser/network collection started.')
        return
    if not args.profile_file: parser.error('--profile-file is required')
    asyncio.run(run(json.loads(args.profile_file.read_text())['profile_url']))

if __name__=='__main__': main()
