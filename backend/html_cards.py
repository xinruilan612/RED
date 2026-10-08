"""Offline, measured HTML/CSS renderer for the vendored MIT XHS themes."""
from pathlib import Path
from io import BytesIO
import base64
import html
import os
import re
from backend.contracts import require

VENDOR = Path(__file__).parent / 'vendor/xhs_article'
THEMES = {'xhs-e':'雅刊', 'xhs-a':'暖杏奶咖', 'xhs-b':'雾松青', 'xhs-c':'黛墨描金',
          'xhs-d':'夜读鎏金', 'xhs-f':'粉色王国', 'xhs-g':'乙游夜境', 'xhs-h':'自然手记'}
VERSION = 1


def browser_arguments():
    configured = os.environ.get('YOUJI_CHROMIUM_EXECUTABLE')
    chrome = Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
    return {'executable_path': configured} if configured else ({'executable_path': str(chrome)} if chrome.is_file() else {})


def available():
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            executable = browser_arguments().get('executable_path', p.chromium.executable_path)
            return Path(executable).is_file() and os.access(executable, os.X_OK)
    except (ImportError, OSError, RuntimeError):
        return False


def _uri(image):
    buffer=BytesIO();image.save(buffer,format='PNG')
    return 'data:image/png;base64,'+base64.b64encode(buffer.getvalue()).decode()


def _shell(theme, style):
    letter=theme[-1]
    classes={'a':'card skin-a','b':'card skin-b','c':'card skin-c','d':'dcard','e':'ecard',
             'f':'femcard t-pink','g':'femcard t-otome','h':'femcard t-ghibli'}[letter]
    deco=(VENDOR/f'deco-{letter}.html').read_text() if letter in 'fgh' else ('<div class="d-frame"></div>' if letter=='d' else '<div class="cv-frame"></div>' if letter=='c' else '<div class="cv-deco"></div>' if letter=='a' else '')
    css='\n'.join((VENDOR/name).read_text() for name in ('styles.css','styles-d.css','styles-e.css','styles-fem.css'))
    accent=style.get('accent','default')
    palette = {'green':'#86c9aa','orange':'#edac7d','blue':'#8cbcef'} if letter in 'dg' else {'green':'#39755f','orange':'#a95228','blue':'#326ba6'}
    color=palette.get(accent)
    override=f'--accent:{color};--gold:{color};--accent-2:{color};--accent2:{color};' if color else ''
    size=44 if style.get('size')=='large' else 38
    css+='''
html,body{margin:0;padding:0;background:white}*{box-sizing:border-box} .youji-page{margin:0;position:relative;break-after:page}
.youji-header{position:absolute;top:65px;left:88px;right:88px;display:flex;justify-content:space-between;font:600 24px/1.4 var(--sans);z-index:5;color:var(--ink,var(--cream))}
.youji-footer{position:absolute;bottom:50px;left:88px;right:88px;font:20px/1.5 var(--sans);z-index:5;color:var(--soft,var(--ink-soft));display:flex;justify-content:space-between;gap:25px}
.youji-tags{position:absolute;left:88px;right:88px;bottom:93px;font:22px/1.3 var(--sans);color:var(--soft,var(--ink-soft));z-index:5;overflow-wrap:anywhere}
.youji-content{position:absolute;left:88px;right:88px;top:155px;bottom:135px;z-index:3;display:flex;flex-direction:column;gap:30px}
.youji-content h1{font-size:92px;line-height:1.28;margin:45px 0 20px;overflow-wrap:anywhere;text-wrap:balance;color:var(--ink,var(--cream));font-family:var(--title-font,var(--e-serif,var(--sans)))}
.dcard h1{font-family:var(--serif);color:var(--cream)}.ecard h1{font-family:var(--e-serif);font-weight:500}.skin-c h1{font-family:var(--serif)}
.youji-image{width:100%;height:305px;object-fit:contain;flex:none;border-radius:12px;background:var(--surface,var(--paper,rgba(255,255,255,.06)))}
.youji-cover .youji-image{height:465px;margin-top:auto}.skin-b.youji-cover .youji-image{order:-1;height:440px;margin:0 0 12px}.skin-b.youji-cover h1{margin-top:0}
.youji-flow{display:flex;flex-direction:column;gap:23px}.youji-flow p{margin:0;white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.65;color:var(--ink,var(--cream));font-family:var(--e-serif,var(--sans));font-weight:400}
.youji-sub{font:24px/1.5 var(--sans);letter-spacing:2px;color:var(--accent,var(--soft));border-bottom:1px solid var(--line);padding-bottom:16px}
.femcard .youji-content{top:175px}.femcard .youji-image{border:3px solid var(--line);border-radius:var(--radius-img)}
.skin-c .cv-frame{position:absolute;inset:40px;border:1px solid var(--accent)}.youji-cover .cv-deco{position:absolute;width:400px;height:400px;border-radius:50%;right:-100px;top:-100px;background:var(--accent-soft)}
'''
    css+=f'.youji-page{{{override}}}.youji-flow p{{font-size:{size}px}}'
    if color: css+=f'.youji-header,.youji-page .youji-content h1{{color:{color}}}.youji-sub{{color:{color};border-color:{color}}}'
    return css,classes,deco


def compose(snapshot, theme, options):
    from backend.card_layout import normalize_options
    from backend.product_photos import catalog_images,photo_identity
    require(theme in THEMES,'INVALID_INPUT','图卡模板不存在')
    normalized,cover=normalize_options(options)
    photo=snapshot.get('product_photo')
    images=catalog_images(photo) if photo and photo.get('photos') else ([cover] if cover else [])
    photo_identity(normalized,photo)
    style=normalized.get('global_style',{'accent':'default','size':'normal'})
    content=snapshot['content'];title=content['selected_title']
    body=content['body']+ ('\n\n'+content['cta'] if content.get('cta') else '')
    tag_text=' '.join('#'+str(tag) for tag in content.get('tags',[]))
    require(len(title)<=500 and len(body)<=30000,'INVALID_INPUT','稿件太长，请缩短后制作图片')
    css,classes,deco=_shell(theme,style)
    pages=[];metadata=[]
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,**browser_arguments())
            try:
                page=browser.new_page(viewport={'width':1080,'height':1440},device_scale_factor=1)
                page.route('**/*',lambda route:route.abort())
                page.set_content('<!doctype html><html lang="zh"><meta charset="utf-8"><style>'+css+'</style><body></body></html>')
                def add_page(cover_page=False):
                    index=len(metadata);picture=images[index] if index<len(images) else None
                    info=(photo or {}).get('photos',[])
                    item=info[index] if index<len(info) else {}
                    metadata.append({'title':title if cover_page else f'正文 · 第{index}页','notice':'', 'photo_id':item.get('id') or ('user-upload' if picture else None),'photo_sha256':item.get('sha256') or (normalized.get('image_sha256') if picture else None),'photo_source_url':item.get('source_url'),'text_blocks':[]})
                    attribution='图片：'+item['author']+' / '+item['license'] if item else ''
                    image='<img class="youji-image" src="'+_uri(picture)+'" />' if picture else ''
                    intro='<h1>'+html.escape(title)+'</h1>' if cover_page else '<div class="youji-sub">'+html.escape(title)+'</div>'
                    markup=f'<section id="p{index}" class="{classes} youji-page '+('youji-cover' if cover_page else '')+'">'+deco+'<div class="youji-header"><span>有迹 · '+THEMES[theme]+'</span><span class="page-number"></span></div><div class="youji-content">'+intro+image+'<div class="youji-flow"></div></div><div class="youji-footer"><span>'+attribution+'</span><span>有迹 · 图文笔记</span></div></section>'
                    page.evaluate('(s)=>document.body.insertAdjacentHTML("beforeend",s)',markup)
                    return index
                add_page(True)
                # Fit long titles visibly, without clipping or silently truncating.
                cover_fits=page.evaluate('''()=>{const root=document.querySelector('.youji-cover .youji-content'),h=root.querySelector('h1');const fits=()=>root.scrollHeight<=root.clientHeight+1;while(!fits() && parseFloat(getComputedStyle(h).fontSize)>24)h.style.fontSize=(parseFloat(getComputedStyle(h).fontSize)-2)+'px';return fits()}''')
                require(cover_fits,'INVALID_INPUT','标题过长，封面无法完整显示，请缩短标题')
                index=add_page()
                def fits(text):
                    return page.evaluate('''({index,text})=>{let root=document.querySelector('#p'+index+' .youji-content'),flow=root.querySelector('.youji-flow'),p=document.createElement('p');p.textContent=text;flow.append(p);let fits=p.getBoundingClientRect().bottom<=root.getBoundingClientRect().bottom+0.5;p.remove();return fits}''',{'index':index,'text':text})
                def append(text):
                    page.evaluate('''({index,text})=>{let p=document.createElement('p');p.textContent=text;document.querySelector('#p'+index+' .youji-flow').append(p)}''',{'index':index,'text':text})
                    metadata[index]['text_blocks'].append(text)
                # Paragraphs stay intact where possible; long ones split on sentence boundaries.
                queue=[s for s in re.split(r'\n\s*\n|\n(?=[①②③④⑤⑥⑦⑧⑨⑩])',body) if s.strip()]
                while queue:
                    text=queue.pop(0)
                    if fits(text):append(text);continue
                    if metadata[index]['text_blocks']:
                        require(len(metadata)<24,'INVALID_INPUT','正文超过24页，请缩短稿件')
                        index=add_page();queue.insert(0,text);continue
                    pieces=re.findall(r'.*?[。！？；](?:[”’」』])?|.+$',text,re.S)
                    if len(pieces)>1:
                        queue=pieces+queue;continue
                    lo,hi=1,len(text)
                    while lo<hi:
                        mid=(lo+hi+1)//2
                        if fits(text[:mid]):lo=mid
                        else:hi=mid-1
                    require(fits(text[:lo]),'INVALID_INPUT','字号过大，当前页面无法容纳正文')
                    append(text[:lo]);queue.insert(0,text[lo:]) if text[lo:] else None
                # Tags belong to the final card's compact footer, never a full body page.
                # The 44px band is between the content bottom (1305) and footer top (1360).
                if tag_text:
                    tags_fit=page.evaluate('''({index,text})=>{const root=document.querySelector('#p'+index),el=document.createElement('div');el.className='youji-tags';el.textContent=text;root.append(el);while(el.getBoundingClientRect().height>44 && parseFloat(getComputedStyle(el).fontSize)>14)el.style.fontSize=(parseFloat(getComputedStyle(el).fontSize)-1)+'px';return el.getBoundingClientRect().height<=44}''',{'index':index,'text':tag_text})
                    require(tags_fit,'INVALID_INPUT','标签过长，无法完整放入末页，请缩短标签')
                    metadata[index]['tags']=tag_text
                for i,meta in enumerate(metadata):
                    page.locator(f'#p{i} .page-number').evaluate('(el,t)=>el.textContent=t',f'{i+1:02d} / {len(metadata):02d}')
                    bounds=page.locator(f'#p{i} .youji-content').evaluate('''el=>({overflow:el.scrollHeight>el.clientHeight+1,right:[...el.querySelectorAll('h1,p,img')].some(x=>x.getBoundingClientRect().right>el.getBoundingClientRect().right+1)})''')
                    require(not bounds['overflow'] and not bounds['right'],'INVALID_INPUT','图卡内容超出页面，请调整字号或缩短标题')
                    meta['layout_verified']=True
                    pages.append((f'{i+1:02d}.png',page.locator(f'#p{i}').screenshot(animations='disabled')))
            finally:browser.close()
    except ImportError:
        require(False,'MEDIA_UNAVAILABLE','请安装 playwright==1.60.0 并运行 python -m playwright install chromium')
    except Exception as error:
        from backend.contracts import DomainError
        if isinstance(error,DomainError):raise
        require(False,'MEDIA_UNAVAILABLE','图卡浏览器渲染失败，请检查 Chromium 安装后重试')
    return pages,metadata,normalized
