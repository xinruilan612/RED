"""Owner-scoped design sessions; render candidates before atomic version checks."""
import base64
from copy import deepcopy
from io import BytesIO
import json
import math
import re
from uuid import uuid4
from backend.contracts import DomainError, require
from backend.workflow import digest
from backend.media_exports import confirmed_snapshot, preview_run, export_run


def _snapshot(run,data=None):
    snap=confirmed_snapshot(run)
    if data is not None:
        require(data.get('draft_ref')==snap['draft_ref'] and data.get('content_hash')==snap['content_hash'],'VERSION_CONFLICT','稿件已变化，请重新打开图文共创')
    return snap


def _load(db,run,snap):
    row=db.execute('SELECT payload FROM studio_sessions WHERE run_id=? AND owner=? AND draft_ref=? AND content_hash=?',(run.run_id,run.owner_id,snap['draft_ref'],snap['content_hash'])).fetchone()
    return json.loads(row[0]) if row else None


def _public(state):
    out={k:deepcopy(v) for k,v in state.items() if k not in ('history','cursor')}
    out.update(has_pending=state['current']!=state['accepted'],can_undo=state.get('can_undo',state.get('cursor',0)>0),can_redo=state.get('can_redo',state.get('cursor',0)<len(state.get('history',[]))-1))
    return out


def _hydrated(design,assets):
    result=deepcopy(design)
    studio=result['options'].get('studio')
    if studio is not None:
        ids={page.get('image',{}).get('asset_id') for page in studio.get('pages',{}).values()}
        studio['assets']={a['id']:a['data_url'] for a in assets if a['id'] in ids}
    return result


def _render(run,design,assets): return preview_run(run,**_hydrated(design,assets))


def _replay_state(db,run,snap,payload):
    saved=json.loads(payload); latest=_load(db,run,snap)
    assets={a['id']:a for a in latest['assets']} if latest else {}
    saved['assets']=[assets[a['id']] for a in saved['assets'] if a['id'] in assets]
    return saved


def _response(run,state,preview=None):
    preview=preview if preview is not None else _render(run,state['current'],state['assets'])
    accepted=_render(run,state['accepted'],state['assets']) if state['current']!=state['accepted'] else preview
    return {'state':_public(state),'preview':preview,'accepted_preview':accepted}


def read(store,owner,run_id):
    with store.connect() as db:
        run=store._get(db,run_id,owner); snap=_snapshot(run); state=_load(db,run,snap)
    return _response(run,state) if state else {'state':None,'preview':None,'accepted_preview':None}


def _asset(data):
    from backend.card_layout import normalize_options
    require(isinstance(data,dict) and set(data)<={'name','role','data_url'},'INVALID_INPUT','素材字段无效')
    require(isinstance(data.get('name'),str) and 1<=len(data['name'])<=160,'INVALID_INPUT','素材名称无效')
    require(data.get('role') in ('product','reference'),'INVALID_INPUT','请选择产品图或参考图')
    _,image=normalize_options({'cover_image':data.get('data_url')})
    require(image is not None,'INVALID_INPUT','请上传图片')
    buf=BytesIO(); image.save(buf,format='PNG')
    while len(buf.getvalue())>3*1024*1024:
        image.thumbnail((int(image.width*.8),int(image.height*.8))); buf=BytesIO(); image.save(buf,format='PNG')
    return {'id':uuid4().hex,'name':data['name'],'role':data['role'],'data_url':'data:image/png;base64,'+base64.b64encode(buf.getvalue()).decode()}


def apply_operations(design,operations,assets,page_count):
    from backend.html_cards import THEMES
    require(isinstance(operations,list) and 1<=len(operations)<=32,'INVALID_INPUT','一次修改需包含1至32个操作')
    result=deepcopy(design)
    for op in operations:
        require(isinstance(op,dict),'INVALID_INPUT','修改操作无效')
        if set(op)=={'template'}:
            require(isinstance(op['template'],str) and op['template'] in THEMES,'INVALID_INPUT','模板不存在')
            result['template']=op['template']; continue
        require(set(op)<={'page_index','element_id','changes','layout'} and 'page_index' in op,'INVALID_INPUT','修改操作字段无效；改写文案请返回稿件编辑并重新审核')
        idx=op['page_index']; require(type(idx) is int and 0<=idx<page_count,'INVALID_INPUT','所选页面不存在')
        page=result['options'].setdefault('studio',{}).setdefault('pages',{}).setdefault(str(idx),{})
        if 'layout' in op:
            require(isinstance(op['layout'],str) and op['layout'] in ('hero','checklist','compare'),'INVALID_INPUT','版式无效')
            page['layout']=op['layout']
        if 'changes' not in op:
            require('layout' in op and 'element_id' not in op,'INVALID_INPUT','修改内容为空'); continue
        element=op.get('element_id'); changes=op['changes']
        require(isinstance(element,str) and element in ('title','image','body','background'),'INVALID_INPUT','请选择标题、图片、正文或背景')
        allowed={'background':{'color'},'image':{'dx','dy','scale','asset_id','placement'}}.get(element,{'dx','dy','scale','color','opacity'})
        require(isinstance(changes,dict) and bool(changes) and set(changes)<=allowed,'INVALID_INPUT','修改属性无效；已确认文案请通过稿件编辑修改')
        for key,value in changes.items():
            if key in ('dx','dy','scale'):
                low,high=(.5,1.6) if key=='scale' else (-350,350)
                require(type(value) in (int,float) and math.isfinite(value) and low<=value<=high,'INVALID_INPUT','移动或缩放超出允许范围')
            elif key=='opacity': require(type(value) in (int,float) and math.isfinite(value) and 0<=value<=1,'INVALID_INPUT','文字不透明度必须在0至1之间')
            elif key=='placement': require(value in ('background','inline'),'INVALID_INPUT','图片位置必须为背景或行内')
            elif key=='color': require(isinstance(value,str) and re.fullmatch(r'#[0-9a-fA-F]{6}',value),'INVALID_INPUT','颜色必须为六位十六进制值')
            else:
                require(isinstance(value,str) and any(a['id']==value and a['role']=='product' for a in assets),'INVALID_INPUT','替换图片必须使用本任务的产品素材')
        page.setdefault(element,{}).update(changes)
    return result


def describe_changes(before,after):
    """Report committed parameter differences, never model-authored success claims."""
    labels={'title':'标题','body':'正文','image':'产品图','background':'背景'}
    changes=[]
    if before['template']!=after['template']: changes.append('整套主题切换为 '+after['template'])
    old_pages=before['options'].get('studio',{}).get('pages',{})
    for index,page in after['options'].get('studio',{}).get('pages',{}).items():
        previous=old_pages.get(index,{})
        for element,values in page.items():
            prefix=f'第{int(index)+1}张'
            if element=='layout':
                if previous.get(element)!=values: changes.append(prefix+'构图改为 '+{'hero':'大图主视觉','checklist':'清单卡片','compare':'图文对照'}[values])
                continue
            for key,value in values.items():
                default={'scale':1,'dx':0,'dy':0,'opacity':1,'placement':'inline'}.get(key)
                if previous.get(element,{}).get(key,default)==value: continue
                text={'placement':'设为铺满画布的背景图' if value=='background' else '恢复行内图片',
                      'opacity':f'不透明度设为 {value*100:g}%' if key=='opacity' else '',
                      'scale':f'缩放设为 {value*100:g}%' if key=='scale' else '',
                      'dx':f'水平偏移设为 {value}' ,'dy':f'垂直偏移设为 {value}',
                      'color':f'颜色设为 {value}','asset_id':'替换为所选产品素材'}[key]
                changes.append(prefix+labels[element]+text)
    return '已应用：'+'；'.join(changes)+'。' if changes else '画布参数未发生有效变化。'


def _checkpoint(state,design):
    if design==state['current']: return False
    state['history']=(state['history'][:state['cursor']+1]+[deepcopy(design)])[-60:]
    state['cursor']=len(state['history'])-1; state['current']=deepcopy(design)
    return True


def mutate(store,owner,run_id,data):
    fields={'action','expected_revision','draft_ref','content_hash','idempotency_key','template','options','operations','feedback','page_index','element_id','region','asset','reference_asset_id'}
    require(isinstance(data,dict) and set(data)<=fields,'INVALID_INPUT','共创请求字段无效')
    action=data.get('action'); key=data.get('idempotency_key')
    require(isinstance(action,str) and action in ('init','edit','accept','undo','redo','discard','asset'),'INVALID_INPUT','共创操作无效')
    require(isinstance(key,str) and 1<=len(key)<=128,'INVALID_INPUT','共创操作缺少幂等键')
    require(action=='init' or type(data.get('expected_revision')) is int,'INVALID_INPUT','请提供当前版本')
    try: fingerprint=digest({'run_id':run_id,'data':data})
    except (ValueError,TypeError): raise DomainError('INVALID_INPUT','共创请求包含无效数值或数据类型')
    with store.connect() as db:
        run=store._get(db,run_id,owner); snap=_snapshot(run,data)
        replay=db.execute('SELECT fingerprint,response FROM studio_commands WHERE owner=? AND key=?',(owner,key)).fetchone()
        if replay:
            require(replay[0]==fingerprint,'IDEMPOTENCY_CONFLICT','幂等键已用于其他操作')
            return _response(run,_replay_state(db,run,snap,replay[1]))
        state=_load(db,run,snap)
    previous=state['revision'] if state else None
    if action=='init':
        if state is None:
            from backend.html_cards import THEMES
            template=data.get('template','xhs-e')
            require(isinstance(template,str) and template in THEMES,'INVALID_INPUT','共创模板不存在')
            design={'template':template,'options':deepcopy(data.get('options') or {})}
            require(isinstance(design['options'],dict),'INVALID_INPUT','排版设置无效')
            if 'studio' in design['options']:
                initial=design['options']['studio']
                require(isinstance(initial,dict) and set(initial)=={'pages'} and isinstance(initial['pages'],dict) and len(initial['pages'])<=24,'INVALID_INPUT','首次共创仅支持选择初始版式')
                for page,row in initial['pages'].items():
                    require(isinstance(page,str) and re.fullmatch(r'0|[1-9]\d?',page) and int(page)<24 and isinstance(row,dict) and set(row)=={'layout'} and isinstance(row['layout'],str) and row['layout'] in ('hero','checklist','compare'),'INVALID_INPUT','首次共创仅支持选择初始版式')
            assets=[]
            if design['options'].get('cover_image'):
                assets=[_asset({'name':'原封面图片','role':'product','data_url':design['options'].pop('cover_image')})]
                design['options'].setdefault('studio',{}).setdefault('pages',{}).setdefault('0',{})['image']={'asset_id':assets[0]['id']}
            state={'revision':0,'current':design,'accepted':deepcopy(design),'assets':assets,'messages':[],'history':[deepcopy(design)],'cursor':0,'draft_ref':snap['draft_ref'],'content_hash':snap['content_hash']}
    else:
        require(state is not None,'INVALID_TRANSITION','请先打开图文共创')
        require(data['expected_revision']==state['revision'],'VERSION_CONFLICT','排版已在其他操作中变化，请刷新后继续')
        state=deepcopy(state)
    preview=None
    if action=='edit':
        before=_render(run,state['current'],state['assets'])
        require(('operations' in data) != ('feedback' in data),'INVALID_INPUT','请选择直接调整或对话修改')
        if 'feedback' in data:
            feedback=data['feedback']
            require(isinstance(feedback,str) and 1<=len(feedback.strip())<=1000,'INVALID_INPUT','请输入1至1000字修改意见')
            idx=data.get('page_index'); element=data.get('element_id')
            require(type(idx) is int and 0<=idx<len(before['pages']),'INVALID_INPUT','请选择当前页面')
            require(element is None or (isinstance(element,str) and element in ('title','image','body','background')),'INVALID_INPUT','选中对象无效')
            from backend.model_router import Calls
            result=Calls.invoke_studio_vision(store,run,before,state,feedback,idx,element,data.get('region'),reference_asset_id=data.get('reference_asset_id'))
            state['messages'].append({'role':'user','text':feedback,'page_index':idx,'element_id':element})
            state['messages'].append({'role':'assistant','text':'此次请求未执行：'+result['reason'] if result['unsupported'] else '', 'observation':'','call_id':result['call_id'],'operations':deepcopy(result['operations'])})
            operations=result['operations']
            if result['unsupported']:
                require(not operations,'LOCAL_VISION_INVALID','模型同时返回不支持和修改操作'); preview=before
                state['last_edit_changed']=False
            else:
                old_design=deepcopy(state['current'])
                changed=_checkpoint(state,apply_operations(state['current'],operations,state['assets'],len(before['pages'])))
                state['messages'][-1]['text']=describe_changes(old_design,state['current'])
                state['last_edit_changed']=changed
                state['messages'][-1]['changed']=changed
                if not changed:
                    state['messages'][-1]['text']='提案与当前参数相同，画布未变化。请补充希望调整到的大小、位置或颜色。'
                    state['messages'][-1]['operations']=[]
            # Only successfully rendered changes will be committed below.
        else:
            state['last_edit_changed']=_checkpoint(state,apply_operations(state['current'],data['operations'],state['assets'],len(before['pages'])))
    elif action=='asset':
        require(len(state['assets'])<6,'INVALID_INPUT','一个任务最多上传6张素材')
        state['assets'].append(_asset(data.get('asset')))
    elif action=='accept': state['accepted']=deepcopy(state['current'])
    elif action=='discard': _checkpoint(state,state['accepted'])
    elif action in ('undo','redo'):
        cursor=state['cursor']+(-1 if action=='undo' else 1)
        require(0<=cursor<len(state['history']),'INVALID_TRANSITION','没有可撤销或重做的修改')
        state['cursor']=cursor; state['current']=deepcopy(state['history'][cursor])
    state['messages']=state['messages'][-60:]
    if previous is not None and action!='init': state['revision']=previous+1
    if preview is None: preview=_render(run,state['current'],state['assets'])
    # Verify both sides of the comparison before publishing a version.
    response=_response(run,state,preview)
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        latest=store._get(db,run_id,owner); _snapshot(latest,data)
        replay=db.execute('SELECT fingerprint,response FROM studio_commands WHERE owner=? AND key=?',(owner,key)).fetchone()
        if replay:
            require(replay[0]==fingerprint,'IDEMPOTENCY_CONFLICT','幂等键已用于其他操作')
            return _response(latest,_replay_state(db,latest,snap,replay[1]))
        current=_load(db,latest,snap)
        require((current['revision'] if current else None)==previous,'VERSION_CONFLICT','排版已变化，此次迟到结果未写入，请重新操作')
        payload=json.dumps(state,ensure_ascii=False)
        db.execute('INSERT INTO studio_sessions(run_id,owner,draft_ref,content_hash,revision,payload) VALUES(?,?,?,?,?,?) ON CONFLICT(run_id,draft_ref,content_hash) DO UPDATE SET revision=excluded.revision,payload=excluded.payload',(run_id,owner,snap['draft_ref'],snap['content_hash'],state['revision'],payload))
        command=_public(state); command['assets']=[{k:v for k,v in a.items() if k!='data_url'} for a in state['assets']]
        db.execute('INSERT INTO studio_commands(owner,key,fingerprint,response) VALUES(?,?,?,?)',(owner,key,fingerprint,json.dumps(command,ensure_ascii=False)))
    return response


def export(store,owner,run_id,data,execution=None):
    require(isinstance(data,dict) and set(data)<={'kind','expected_revision','draft_ref','content_hash'},'INVALID_INPUT','导出请求无效')
    with store.connect() as db:
        run=store._get(db,run_id,owner); snap=_snapshot(run,data); state=_load(db,run,snap)
    require(state is not None and type(data.get('expected_revision')) is int and data['expected_revision']==state['revision'],'VERSION_CONFLICT','排版已变化，请刷新后导出')
    require(state['current']==state['accepted'],'INVALID_TRANSITION','请先采用或放弃待确认修改，再导出成品')
    result=export_run(run,data.get('kind','images'),execution=execution,**_hydrated(state['accepted'],state['assets']))
    with store.connect() as db:
        latest=store._get(db,run_id,owner); _snapshot(latest,data); current=_load(db,latest,snap)
        require(current is not None and current['revision']==state['revision'],'VERSION_CONFLICT','导出期间排版已变化，请重新导出')
    return result
