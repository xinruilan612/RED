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
    cut=min(candidates,key=lambda n:abs(n-len(text)/2))
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
    require(action in ('split','remove_photo'),'ADJUST_UNSUPPORTED','本次试用支持拆分正文页或移除本页图片；文字润色请到改稿区处理。原图保留。')
    pages=[{'text_blocks':list(p.get('text_blocks',[])),'photo_index':p.get('photo_index')} for p in before['pages']]
    require(all('photo_index' in p for p in before['pages']),'VERSION_CONFLICT','预览信息已更新，请刷新页面')
    if action=='split':
        require(index>0,'INVALID_INPUT','封面不能拆分；请先选择正文图卡')
        require(len(pages)<24,'INVALID_INPUT','图片已达到24页，无法继续拆分')
        left,right=split_blocks(pages[index]['text_blocks'])
        pages[index:index+1]=[{'text_blocks':left,'photo_index':pages[index]['photo_index']},{'text_blocks':right,'photo_index':None}]
        summary=f'第 {index+1} 张拆成两张，文字全部保留；原照片保留在前一张，后一张只排文字。其他页内容不变。'
    else:
        require(pages[index]['photo_index'] is not None,'INVALID_INPUT','这一页没有产品图片，无需移除；原图保留')
        pages[index]['photo_index']=None
        summary=f'仅移除第 {index+1} 张的产品图片，保留全部文字；其他页内容不变。'
    options=deepcopy(data.get('options') or {})
    options['layout_plan']={'pages':pages}
    after=preview_run(run,template=data['template'],options=options)
    return {'mode':'local_vision','model':result.get('model','qwen3-vl:4b'),'observation':result.get('observation',''),
            'summary':summary,'reason':result.get('reason',''),'call_id':result.get('call_id'),
            'before_page_index':index,'after_page_indices':[index,index+1] if action=='split' else [index],
            'preview':after,'options':options}
