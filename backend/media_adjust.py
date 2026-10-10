"""Image-aware layout proposals. Never rewrites an accepted content draft."""
from copy import deepcopy
import re
from backend.contracts import require


def split_blocks(blocks):
    """Split at the nearest sentence/paragraph boundary, preserving every character."""
    text=''.join(blocks)
    candidates=[]
    offset=0
    for block in blocks:
        for match in re.finditer(r'[。！？；!?;](?:[”’」』])?',block):
            candidates.append(offset+match.end())
        offset+=len(block)
        candidates.append(offset)
    candidates=[n for n in candidates if text[:n].strip() and text[n:].strip()]
    require(candidates,'INVALID_INPUT','这一页没有合适的句段分界，无法拆成两页；原图保留')
    # Keep an existing numbered point together before falling back to sentences.
    point_starts=[m.start() for m in re.finditer(r'[①②③④⑤⑥⑦⑧⑨⑩]',text)]
    point_boundaries=[n for n in point_starts[1:] if text[:n].strip() and text[n:].strip()]
    cut=min(point_boundaries or candidates,key=lambda n:abs(n-len(text)/2))
    left=[];right=[];offset=0
    for block in blocks:
        local=max(0,min(len(block),cut-offset))
        if block[:local]:left.append(block[:local])
        if block[local:]:right.append(block[local:])
        offset+=len(block)
    return left,right


def propose(run,data,before,result):
    from backend.media_exports import preview_run
    from backend.html_cards import THEMES
    require(data.get('template') in THEMES,'INVALID_INPUT','请先选择当前模板库中的图卡')
    action=result.get('action');index=data['page_index']
    require(action in ('split','remove_photo','photo_below','photo_above','center_points','align_left'),'ADJUST_UNSUPPORTED','每次只支持一种操作：拆页、移除图片、图片放正文上方或下方、正文分点居中或左对齐。组合操作与自由改写暂不支持；原图保留。')
    existing=(data.get('options') or {}).get('layout_plan',{}).get('pages',[])
    pages=[]
    for i,p in enumerate(before['pages']):
        prior=existing[i] if i<len(existing) else {}
        pages.append({'text_blocks':list(p.get('text_blocks',[])),'photo_index':p.get('photo_index'),
                      'photo_position':p.get('photo_position',prior.get('photo_position','above')),
                      'text_align':p.get('text_align',prior.get('text_align','center'))})
    require(all('photo_index' in p for p in before['pages']),'VERSION_CONFLICT','预览信息已更新，请刷新页面')
    if action=='split':
        require(index>0,'INVALID_INPUT','封面不能拆分；请先选择正文图卡')
        require(len(pages)<24,'INVALID_INPUT','图片已达到24页，无法继续拆分')
        left,right=split_blocks(pages[index]['text_blocks'])
        pages[index:index+1]=[{**pages[index],'text_blocks':left},{**pages[index],'text_blocks':right,'photo_index':None}]
        summary=f'第 {index+1} 张拆成两张，文字全部保留；原照片保留在前一张，后一张只排文字。其他页内容不变。'
    elif action=='remove_photo':
        require(pages[index]['photo_index'] is not None,'INVALID_INPUT','这一页没有产品图片，无需移除；原图保留')
        pages[index]['photo_index']=None
        summary=f'仅移除第 {index+1} 张的产品图片，保留全部文字；其他页内容不变。'
    elif action in ('photo_below','photo_above'):
        require(index>0,'INVALID_INPUT','封面没有正文区域；请选择有产品图片的正文页')
        require(pages[index]['photo_index'] is not None,'INVALID_INPUT','这一页没有产品图片，无法移动；请选择有产品图片的正文页')
        pages[index]['photo_position']='below' if action=='photo_below' else 'above'
        position='下方' if action=='photo_below' else '上方'
        summary=f'第 {index+1} 张的产品图片放在正文{position}，保留全部文字；其他页内容不变。'
    else:
        require(index>0,'INVALID_INPUT','封面不能调整正文对齐；请先选择正文图卡')
        pages[index]['text_align']='center' if action=='center_points' else 'left'
        alignment='按原编号分点居中' if action=='center_points' else '左对齐'
        summary=f'第 {index+1} 张正文{alignment}，保留全部文字和图片；其他页内容不变。'
    options=deepcopy(data.get('options') or {})
    options['layout_plan']={'pages':pages}
    after=preview_run(run,template=data['template'],options=options)
    return {'mode':'local_vision','model':result.get('model','qwen3-vl:4b'),'observation':result.get('observation',''),
            'summary':summary,'reason':result.get('reason',''),'call_id':result.get('call_id'),
            'before_page_index':index,'after_page_indices':[index,index+1] if action=='split' else [index],
            'preview':after,'options':options}
