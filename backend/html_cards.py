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
VERSION = 2


def browser_arguments():
    configured = os.environ.get('YOUJI_CHROMIUM_EXECUTABLE')
    chrome = Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
    if configured: return {'executable_path': configured}
    if os.environ.get('PLAYWRIGHT_BROWSERS_PATH'): return {}
    return {'executable_path': str(chrome)} if chrome.is_file() else {}


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
    font = os.environ.get('YOUJI_CJK_FONT', '')
    if font and Path(font).is_file():
        encoded = base64.b64encode(Path(font).read_bytes()).decode('ascii')
        css += f'@font-face{{font-family:YoujiCJK;src:url(data:font/otf;base64,{encoded})}}:root{{--sans:YoujiCJK,sans-serif;--serif:YoujiCJK,serif;--title-font:YoujiCJK;--e-serif:YoujiCJK}}'
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
.youji-bodygroup{display:flex;flex-direction:column;gap:30px;flex:1;min-height:0}.youji-bodygroup.ready{justify-content:center}.youji-bodygroup>*{flex-shrink:0}.youji-bodygroup .youji-flow{text-align:center}.youji-bodygroup.align-left .youji-flow{text-align:left}.youji-bodygroup.photo-below .youji-image{order:2}
.youji-flow{display:flex;flex-direction:column;gap:23px}.youji-flow p{margin:0;white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.65;color:var(--ink,var(--cream));font-family:var(--e-serif,var(--sans));font-weight:400}
.youji-sub{font:24px/1.5 var(--sans);letter-spacing:2px;color:var(--accent,var(--soft));border-bottom:1px solid var(--line);padding-bottom:16px}
.femcard .youji-content{top:175px}.femcard .youji-image{border:3px solid var(--line);border-radius:var(--radius-img)}
.skin-c .cv-frame{position:absolute;inset:40px;border:1px solid var(--accent)}.youji-cover .cv-deco{position:absolute;width:400px;height:400px;border-radius:50%;right:-100px;top:-100px;background:var(--accent-soft)}
'''
    css+=f'.youji-page{{{override}}}.youji-flow p{{font-size:{size}px}}'
    if color: css+=f'.youji-header,.youji-page .youji-content h1{{color:{color}}}.youji-sub{{color:{color};border-color:{color}}}'
    return css,classes,deco


def point_blocks(blocks):
    # Preserve wording; give existing numbered points their own paragraphs.
    return [part for block in blocks for part in re.split(r'\n\s*\n|(?=[①②③④⑤⑥⑦⑧⑨⑩])',block) if part.strip()]

# Browser-side scene finalization uses the same DOM for preview and exported PNG.
STUDIO_SCENE = r'''({index,patch})=>{
 const root=document.querySelector('#p'+index), rr=root.getBoundingClientRect();
 const backgroundImage=patch.image?.placement==='background';
 const active=!!patch.layout||Object.entries(patch).some(([id,cfg])=>id!=='layout'&&Object.entries(cfg).some(([key,value])=>(key==='scale'||key==='opacity')?value!==1:key==='placement'?value!=='inline':(key==='dx'||key==='dy')?value!==0:true));
 const nodes={title:root.querySelector('h1,.youji-sub'),image:root.querySelector('.youji-image'),body:root.querySelector('.youji-flow')};
 const box=el=>{const r=el.getBoundingClientRect();return {x:r.left-rr.left,y:r.top-rr.top,width:r.width,height:r.height}};
 const present=Object.entries(nodes).filter(([id,el])=>el&&(id!=='body'||el.textContent.trim()));
 // Metadata selects actual image pixels, not the full-width contain frame.
 const imageBox=el=>{const b=box(el);if(backgroundImage)return b;const ratio=Math.min(b.width/el.naturalWidth,b.height/el.naturalHeight);let w=el.naturalWidth*ratio,h=el.naturalHeight*ratio;return {x:b.x+(b.width-w)/2,y:b.y+(b.height-h)/2,width:w,height:h}};
 const missing=Object.keys(patch).some(id=>id!=='layout'&&id!=='background'&&!present.some(([key])=>key===id));
 const boxes=Object.fromEntries(present.map(([id,el])=>[id,id==='image'?imageBox(el):{...box(el),height:Math.max(box(el).height,el.scrollHeight)}]));
 if(active){
  // Freeze measured content without reflowing or dropping any approved words.
  for(const [id,el] of present){const b=id==='image'?box(el):boxes[id],cs=getComputedStyle(el);const keep={};for(const key of ['font','color','lineHeight','letterSpacing','textAlign','overflowWrap','textWrap'])keep[key]=cs[key];root.append(el);Object.assign(el.style,keep);Object.assign(el.style,{position:'absolute',left:b.x+'px',top:b.y+'px',width:b.width+'px',height:b.height+'px',margin:'0',maxWidth:'none',zIndex:'6',transformOrigin:'center center'});}
  const place=(id,b)=>{const el=nodes[id];if(!el||!boxes[id])return;Object.assign(el.style,{left:b.x+'px',top:b.y+'px',width:b.width+'px',height:b.height+'px'});boxes[id]=b;};
  const fitImage=b=>{if(!nodes.image)return;let ratio=Math.min(b.width/nodes.image.naturalWidth,b.height/nodes.image.naturalHeight),w=nodes.image.naturalWidth*ratio,h=nodes.image.naturalHeight*ratio;place('image',{x:b.x+(b.width-w)/2,y:b.y+(b.height-h)/2,width:w,height:h});};
  const fitText=(id,b)=>{const el=nodes[id];if(!el||!boxes[id])return;place(id,b);el.style.justifyContent='center';el.style.display='flex';if(id==='title')el.style.alignItems='center';const texts=id==='body'?[...el.querySelectorAll('p')]:[el];let size=parseFloat(getComputedStyle(texts[0]).fontSize);while((el.scrollHeight>b.height+1||el.scrollWidth>b.width+1)&&size>22){size--;texts.forEach(n=>n.style.fontSize=size+'px');}};
  const cover=root.classList.contains('youji-cover');
  if(patch.layout){
   root.dataset.studioLayout=patch.layout;
   if(cover){
    if(patch.layout==='compare'&&nodes.image){fitText('title',{x:88,y:260,width:425,height:820});fitImage({x:555,y:260,width:437,height:820});}
    else if(patch.layout==='hero'&&nodes.image){fitText('title',{x:88,y:160,width:904,height:330});fitImage({x:88,y:535,width:904,height:680});}
    else {fitText('title',{x:110,y:200,width:860,height:nodes.image?540:950});fitImage({x:150,y:825,width:780,height:360});nodes.title.style.borderLeft='8px solid var(--accent,#39755f)';nodes.title.style.paddingLeft='32px';}
   } else {
    fitText('title',{x:88,y:155,width:904,height:95});
    if(patch.layout==='compare'&&nodes.image){fitImage({x:88,y:330,width:385,height:800});fitText('body',{x:520,y:295,width:472,height:960});nodes.body.style.textAlign='left';}
    else if(patch.layout==='checklist'){fitText('body',{x:105,y:285,width:870,height:nodes.image?620:965});fitImage({x:230,y:970,width:620,height:280});nodes.body.style.textAlign='left';nodes.body.style.borderLeft='6px solid var(--accent,#39755f)';nodes.body.style.paddingLeft='26px';}
    else {fitImage({x:165,y:290,width:750,height:390});fitText('body',{x:88,y:nodes.image?730:290,width:904,height:nodes.image?515:955});}
   }
  }
  if(backgroundImage&&nodes.image){place('image',{x:0,y:0,width:1080,height:1440});Object.assign(nodes.image.style,{objectFit:'cover',borderRadius:'0',border:'0',background:'transparent',zIndex:'2'});}
  for(const [id,el] of present){const cfg=patch[id]||{};if(cfg.opacity!==undefined)el.style.opacity=String(cfg.opacity);if(!(backgroundImage&&id==='image'))el.style.transform=`translate(${cfg.dx||0}px,${cfg.dy||0}px) scale(${cfg.scale||1})`;if(cfg.color){el.style.color=cfg.color;el.querySelectorAll('p').forEach(n=>n.style.color=cfg.color);}}
  if(patch.background?.color){root.style.setProperty('background',patch.background.color,'important');root.style.setProperty('background-image','none','important');}
 }
 const elements=present.map(([id,el])=>({id,type:id==='image'?'image':'text',bounds:active?(id==='image'?imageBox(el):box(el)):boxes[id],text:id==='image'?undefined:el.textContent,color:getComputedStyle(el).color,opacity:Number(getComputedStyle(el).opacity),...(id==='image'?{placement:backgroundImage?'background':'inline'}:{})}));
 const within=elements.every(({id,bounds:b})=>backgroundImage&&id==='image'?b.x===0&&b.y===0&&b.width===1080&&b.height===1440:b.x>=40&&b.y>=125&&b.x+b.width<=1040&&b.y+b.height<=1305);
 const overlaps=(a,b)=>a.x<b.x+b.width-1&&a.x+a.width>b.x+1&&a.y<b.y+b.height-1&&a.y+a.height>b.y+1;
 const collision=elements.some((a,i)=>elements.slice(i+1).some(b=>!(backgroundImage&&(a.id==='image'||b.id==='image'))&&overlaps(a.bounds,b.bounds)));
 const full=present.every(([id,el])=>id==='image'||el.scrollHeight<=el.clientHeight+1&&el.scrollWidth<=el.clientWidth+1);
 elements.unshift({id:'background',type:'background',bounds:{x:0,y:0,width:1080,height:1440},color:getComputedStyle(root).backgroundColor});
 return {elements,valid:!missing&&(!active||(within&&!collision&&full)),within,collision,full};
}'''


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
    studio=normalized.get('studio', {'pages': {}, 'assets': {}})
    plan=normalized.get('layout_plan')
    if plan:
        compact=lambda value: re.sub(r'\s+', '', value)
        planned_text=''.join(block for row in plan['pages'][1:] for block in row['text_blocks'])
        require(compact(planned_text)==compact(body),'INVALID_INPUT','排版方案改变或遗漏了已确认文案，请重新生成排版方案')
        selected=[row['photo_index'] for row in plan['pages'] if row['photo_index'] is not None]
        require(all(index < len(images) for index in selected),'INVALID_INPUT','排版方案引用的产品图片不可用')
        require(len(set(selected))==len(selected),'INVALID_INPUT','排版方案不能重复使用同一张产品图片')
    css,classes,deco=_shell(theme,style)
    pages=[];metadata=[]
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            # Software rendering avoids variable image resampling; full rasterization also
            # keeps antialiased decoration edges identical after page-number invalidation.
            browser=p.chromium.launch(headless=True,args=["--disable-gpu", "--disable-partial-raster"],**browser_arguments())
            try:
                page=browser.new_page(viewport={'width':1080,'height':1440},device_scale_factor=1)
                page.route('**/*',lambda route:route.abort())
                page.set_content('<!doctype html><html lang="zh"><meta charset="utf-8"><style>'+css+'</style><body></body></html>')
                def add_page(cover_page=False, photo_index='auto', photo_position='above', text_align='center'):
                    index=len(metadata)
                    if photo_index == 'auto': photo_index=index if index<len(images) else None
                    picture=images[photo_index] if photo_index is not None else None
                    custom=studio['pages'].get(str(index), {}).get('image', {}).get('asset_id')
                    if custom:
                        _,picture=normalize_options({'cover_image':studio['assets'][custom]})
                    info=(photo or {}).get('photos',[])
                    item=info[photo_index] if photo_index is not None and photo_index<len(info) else {}
                    metadata.append({'title':title if cover_page else f'正文 · 第{index}页','notice':'', 'photo_id':item.get('id') or ('user-upload' if picture else None),'photo_sha256':item.get('sha256') or (normalized.get('image_sha256') if picture else None),'photo_source_url':item.get('source_url'),'text_blocks':[], 'photo_index':photo_index, 'photo_position':photo_position, 'text_align':text_align})
                    if custom:
                        import hashlib
                        metadata[-1].update(photo_id=custom, photo_sha256=hashlib.sha256(picture.tobytes()).hexdigest(), photo_source_url=None, photo_index=None)
                        item={}
                    attribution='图片：'+item['author']+' / '+item['license'] if item else ''
                    image='<img class="youji-image" src="'+_uri(picture)+'" />' if picture else ''
                    intro='<h1>'+html.escape(title)+'</h1>' if cover_page else '<div class="youji-sub">'+html.escape(title)+'</div>'
                    group=image+'<div class="youji-flow"></div>'
                    if not cover_page: group=f'<div class="youji-bodygroup photo-{photo_position} align-{text_align}">'+group+'</div>'
                    markup=f'<section id="p{index}" class="{classes} youji-page '+('youji-cover' if cover_page else '')+'">'+deco+'<div class="youji-header"><span>有迹 · '+THEMES[theme]+'</span><span class="page-number"></span></div><div class="youji-content">'+intro+group+'</div><div class="youji-footer"><span>'+attribution+'</span><span>有迹 · 图文笔记</span></div></section>'
                    page.evaluate('(s)=>document.body.insertAdjacentHTML("beforeend",s)',markup)
                    return index
                add_page(True, plan['pages'][0]['photo_index'] if plan else 'auto')
                # Fit long titles visibly, without clipping or silently truncating.
                cover_fits=page.evaluate('''()=>{const root=document.querySelector('.youji-cover .youji-content'),h=root.querySelector('h1');const fits=()=>root.scrollHeight<=root.clientHeight+1;while(!fits() && parseFloat(getComputedStyle(h).fontSize)>24)h.style.fontSize=(parseFloat(getComputedStyle(h).fontSize)-2)+'px';return fits()}''')
                require(cover_fits,'INVALID_INPUT','标题过长，封面无法完整显示，请缩短标题')
                index=0 if plan else add_page()
                def fits(text):
                    return page.evaluate('''({index,text})=>{let root=document.querySelector('#p'+index+' .youji-content'),flow=root.querySelector('.youji-flow'),p=document.createElement('p');p.textContent=text;flow.append(p);let group=root.querySelector('.youji-bodygroup');let fits=group.scrollHeight<=group.clientHeight+0.5;p.remove();return fits}''',{'index':index,'text':text})
                def append(text):
                    page.evaluate('''({index,text})=>{let p=document.createElement('p');p.textContent=text;document.querySelector('#p'+index+' .youji-flow').append(p)}''',{'index':index,'text':text})
                    metadata[index]['text_blocks'].append(text)
                if plan:
                    for row in plan['pages'][1:]:
                        index=add_page(photo_index=row['photo_index'],photo_position=row.get('photo_position','above'),text_align=row.get('text_align','center'))
                        for text in point_blocks(row['text_blocks']):
                            require(fits(text),'INVALID_INPUT',f'排版方案第{index+1}页放不下完整文字，请进一步拆页或减小字号')
                            append(text)
                else:
                    # Paragraphs stay intact where possible; long ones split on sentence boundaries.
                    queue=point_blocks([body])
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
                page.evaluate('''async()=>{await document.fonts.ready;await Promise.all([...document.images].map(im=>im.decode()));await new Promise(requestAnimationFrame)}''')
                page.locator('.youji-bodygroup').evaluate_all('(els)=>els.forEach(el=>el.classList.add("ready"))')
                require(all(int(k)<len(metadata) for k in studio['pages']), 'INVALID_INPUT', '共创页面已变化，请重新选择页面')
                for i,meta in enumerate(metadata):
                    page.locator(f'#p{i} .page-number').evaluate('(el,t)=>el.textContent=t',f'{i+1:02d} / {len(metadata):02d}')
                    bounds=page.locator(f'#p{i} .youji-content').evaluate('''el=>({overflow:el.scrollHeight>el.clientHeight+1,right:[...el.querySelectorAll('h1,p,img')].some(x=>x.getBoundingClientRect().right>el.getBoundingClientRect().right+1)})''')
                    require(not bounds['overflow'] and not bounds['right'],'INVALID_INPUT','图卡内容超出页面，请调整字号或缩短标题')
                    meta['layout_geometry']=page.locator(f'#p{i} .youji-content').evaluate('''el=>{const box=x=>{if(!x)return null;const r=x.getBoundingClientRect(),b=el.getBoundingClientRect();return {top:r.top-b.top,bottom:r.bottom-b.top,height:r.height}};return {height:el.clientHeight,image:box(el.querySelector('img')),text:box(el.querySelector('.youji-flow')),align:getComputedStyle(el.querySelector('.youji-flow')).textAlign}}''')
                    scene=page.evaluate(STUDIO_SCENE, {'index':i, 'patch':studio['pages'].get(str(i), {})})
                    if studio['pages'].get(str(i)):
                        require(scene['valid'], 'INVALID_INPUT', f'第{i+1}页修改导致遮挡或文字超出安全区域，请减小移动或缩放幅度')
                    page.evaluate('''async()=>{await document.fonts.ready;await new Promise(requestAnimationFrame);await new Promise(requestAnimationFrame)}''')
                    meta['elements']=scene['elements']
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
