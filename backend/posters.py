"""Independent raster posters: explicit import, acceptance and durable undo history."""
import base64
import binascii
from copy import deepcopy
from io import BytesIO
import json
import hashlib
import zipfile
import warnings
import time
from uuid import uuid4
from PIL import Image, ImageOps, UnidentifiedImageError
from backend.contracts import DomainError, require
from backend.media_exports import confirmed_snapshot
from backend.workflow import digest

MAX_BYTES=10*1024*1024


def _snapshot(run,data=None):
    snap=confirmed_snapshot(run)
    if data is not None:
        require(data.get('draft_ref')==snap['draft_ref'] and data.get('content_hash')==snap['content_hash'],'VERSION_CONFLICT','稿件已变化，请重新打开海报工作台')
    return snap


def _load(db,run,snap):
    row=db.execute('SELECT payload FROM poster_sessions WHERE run_id=? AND owner=? AND draft_ref=? AND content_hash=?',(run.run_id,run.owner_id,snap['draft_ref'],snap['content_hash'])).fetchone()
    return json.loads(row[0]) if row else None



def _source(db,run,snap):
    """Reuse only this exact confirmed draft's original product asset, never a preview."""
    row=db.execute('SELECT payload FROM studio_sessions WHERE run_id=? AND owner=? AND draft_ref=? AND content_hash=?',(run.run_id,run.owner_id,snap['draft_ref'],snap['content_hash'])).fetchone()
    if row:
        studio=json.loads(row[0]); assets=studio.get('assets',[])
        products=[a for a in assets if isinstance(a,dict) and a.get('role')=='product' and isinstance(a.get('data_url'),str) and a['data_url'].startswith(('data:image/png;base64,','data:image/jpeg;base64,'))]
        by_id={a.get('id'):a for a in products}
        pages=studio.get('current',{}).get('options',{}).get('studio',{}).get('pages',{})
        for index in sorted(pages,key=lambda value: int(value) if str(value).isdigit() else 10000):
            asset=by_id.get(pages[index].get('image',{}).get('asset_id'))
            if asset:
                return {'source_image':asset['data_url'],'source_name':asset.get('name') or '当前图卡产品原图'}
        if products:
            asset=products[-1]
            return {'source_image':asset['data_url'],'source_name':asset.get('name') or '已上传产品原图'}
    from backend.product_photos import resolve_options
    options,photo=resolve_options(snap)
    if photo and options.get('cover_image'):
        return {'source_image':options['cover_image'],'source_name':photo['name']+' · '+photo['author']+' / '+photo['license']}
    return {'source_image':None,'source_name':None}


def _public(db,run,state):
    out={k:deepcopy(v) for k,v in state.items() if k not in ('history','cursor')}
    out.update(has_pending=state['current']!=state['accepted'],can_undo=state['cursor']>0,can_redo=state['cursor']<len(state['history'])-1)
    for key in ('current','accepted'):
        if state[key] is not None:
            row=db.execute('SELECT payload FROM poster_assets WHERE id=? AND owner=? AND run_id=? AND draft_ref=? AND content_hash=?',(state[key],run.owner_id,run.run_id,state['draft_ref'],state['content_hash'])).fetchone()
            require(row is not None,'RESOURCE_NOT_FOUND','海报文件不可访问')
            out[key]=json.loads(row[0])
    return {'state':out,**_source(db,run,_snapshot(run))}


def normalize_image(value):
    require(isinstance(value,str) and len(value)<=MAX_BYTES*4//3+100,'INVALID_INPUT','图片不得超过10MB')
    parts=value.split(',',1)
    require(len(parts)==2 and parts[0] in ('data:image/png;base64','data:image/jpeg;base64'),'INVALID_INPUT','仅支持PNG或JPEG海报')
    try:
        raw=base64.b64decode(parts[1],validate=True)
        require(0<len(raw)<=MAX_BYTES,'INVALID_INPUT','图片不得超过10MB')
        with warnings.catch_warnings():
            warnings.simplefilter('error',Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw)) as source:
                require(source.format in ('PNG','JPEG') and source.width*source.height<=20_000_000 and max(source.size)<=8192,'INVALID_INPUT','海报尺寸超出限制')
                require(not getattr(source,'is_animated',False),'INVALID_INPUT','请使用静态海报')
                image=ImageOps.exif_transpose(source).convert('RGBA' if 'A' in source.getbands() else 'RGB')
                result=BytesIO(); image.save(result,format='PNG'); raw=result.getvalue()
    except (ValueError,binascii.Error,UnidentifiedImageError,OSError,Image.DecompressionBombError,Image.DecompressionBombWarning) as exc:
        raise DomainError('INVALID_INPUT','图片无法读取，请使用有效PNG或JPEG') from exc
    require(len(raw)<=MAX_BYTES,'INVALID_INPUT','规范化PNG超过10MB，请缩小图片后导入')
    return {'data_url':'data:image/png;base64,'+base64.b64encode(raw).decode(),'width':image.width,'height':image.height}


def read(store,owner,run_id):
    with store.connect() as db:
        run=store._get(db,run_id,owner); snap=_snapshot(run); state=_load(db,run,snap)
        return _public(db,run,state) if state else {'state':None,**_source(db,run,snap)}


def mutate(store,owner,run_id,data,*,_generation=None):
    require(isinstance(data,dict),'INVALID_INPUT','海报请求无效')
    action=data.get('action'); key=data.get('idempotency_key')
    require(action in ('init','import','accept','undo','redo'),'INVALID_INPUT','海报操作无效')
    allowed={'action','draft_ref','content_hash','expected_revision','idempotency_key'} | ({'image','prompt','brief'} if action=='import' else set())
    require(set(data)<=allowed,'INVALID_INPUT','海报请求字段无效')
    require(isinstance(key,str) and 1<=len(key)<=128,'INVALID_INPUT','请提供幂等键')
    require(action=='init' or type(data.get('expected_revision')) is int,'INVALID_INPUT','请提供当前版本')
    try: fingerprint=digest({'run_id':run_id,'data':data})
    except (TypeError,ValueError): raise DomainError('INVALID_INPUT','海报数据无效')
    # Authorize before decoding user media; encode once outside the write transaction.
    with store.connect() as db:
        run=store._get(db,run_id,owner); _snapshot(run,data)
    asset=None
    if action=='import':
        for field,limit in (('prompt',16000),('brief',4000)):
            require(isinstance(data.get(field,''),str) and len(data.get(field,''))<=limit,'INVALID_INPUT','海报说明过长或无效')
        asset={**normalize_image(data.get('image')),'id':uuid4().hex,'prompt':data.get('prompt',''),'brief':data.get('brief',''),'source':'imported','content_scope':'independent_poster'}
    if _generation is not None:
        require(asset is not None,'INVALID_INPUT','生成海报必须包含图片')
        asset.update(content_scope='confirmed_copy_composition',source='local_composition',provider='local-pillow',model=None,skill_version=_generation['skill_version'],style=_generation['style'])
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        run=store._get(db,run_id,owner); snap=_snapshot(run,data)
        replay=db.execute('SELECT fingerprint,response FROM poster_commands WHERE owner=? AND key=?',(owner,key)).fetchone()
        if replay:
            require(replay[0]==fingerprint,'IDEMPOTENCY_CONFLICT','幂等键已用于其他操作')
            return _public(db,run,json.loads(replay[1]))
        state=_load(db,run,snap)
        if state is None:
            require(action=='init','INVALID_TRANSITION','请先打开海报工作台')
            state={'revision':0,'draft_ref':snap['draft_ref'],'content_hash':snap['content_hash'],'current':None,'accepted':None,'history':[None],'cursor':0}
        elif action!='init':
            require(data['expected_revision']==state['revision'],'VERSION_CONFLICT','海报已变化，请刷新后继续')
            state['revision']+=1
        if action=='import':
            count=db.execute('SELECT COUNT(*) FROM poster_assets WHERE run_id=? AND owner=? AND draft_ref=? AND content_hash=?',(run_id,owner,snap['draft_ref'],snap['content_hash'])).fetchone()[0]
            require(count<30,'INVALID_INPUT','本稿件已保存30个海报版本，请使用新稿件继续')
            db.execute('INSERT INTO poster_assets(id,run_id,owner,draft_ref,content_hash,payload) VALUES(?,?,?,?,?,?)',(asset['id'],run_id,owner,snap['draft_ref'],snap['content_hash'],json.dumps(asset,ensure_ascii=False)))
            state['history']=(state['history'][:state['cursor']+1]+[asset['id']])[-10:]
            state['cursor']=len(state['history'])-1; state['current']=asset['id']
        elif action=='accept':
            require(state['current'] is not None,'INVALID_TRANSITION','请先导入海报')
            state['accepted']=state['current']
        elif action in ('undo','redo'):
            cursor=state['cursor']+(-1 if action=='undo' else 1)
            require(0<=cursor<len(state['history']),'INVALID_TRANSITION','没有可撤销或重做的海报')
            state['cursor']=cursor; state['current']=state['history'][cursor]
        payload=json.dumps(state,ensure_ascii=False)
        db.execute('INSERT INTO poster_sessions(run_id,owner,draft_ref,content_hash,revision,payload) VALUES(?,?,?,?,?,?) ON CONFLICT(run_id,draft_ref,content_hash) DO UPDATE SET revision=excluded.revision,payload=excluded.payload',(run_id,owner,snap['draft_ref'],snap['content_hash'],state['revision'],payload))
        db.execute('INSERT INTO poster_commands(owner,key,fingerprint,response) VALUES(?,?,?,?)',(owner,key,fingerprint,payload))
        if _generation is not None:
            db.execute("UPDATE poster_generation_calls SET status='SUCCEEDED',result=?,finished=? WHERE id=? AND owner=? AND run_id=? AND status='RUNNING'",(payload,time.time(),_generation['id'],owner,run_id))
        return _public(db,run,state)


def export(store,owner,run_id,data):
    require(isinstance(data,dict) and set(data)<={'draft_ref','content_hash','expected_revision','format','page_index'},'INVALID_INPUT','导出请求无效')
    kind=data.get('format','png')
    require(kind in ('png','zip'),'INVALID_INPUT','请选择PNG或历史全部图片ZIP')
    with store.connect() as db:
        run=store._get(db,run_id,owner); snap=_snapshot(run,data); state=_load(db,run,snap)
        require(state is not None and type(data.get('expected_revision')) is int and data['expected_revision']==state['revision'],'VERSION_CONFLICT','海报已变化，请刷新后导出')
        require(state['accepted'] is not None and state['current']==state['accepted'],'INVALID_TRANSITION','请先采用当前海报，再导出')
        accepted=_public(db,run,state)['state']['accepted']
    pages=accepted.get('pages') or [accepted]
    require(isinstance(pages,list) and 1<=len(pages)<=15,'INVALID_INPUT','历史海报页面无效')
    index=data.get('page_index',0)
    require(type(index) is int and 0<=index<len(pages),'INVALID_INPUT','所选页面不存在')
    files=[(f'{i+1:02d}.png',base64.b64decode(page['data_url'].split(',',1)[1])) for i,page in enumerate(pages)]
    if kind=='png':
        return files[index][1],'image/png',('youji-poster.png' if len(pages)==1 else f'youji-poster-{index+1:02d}.png')
    stream=BytesIO()
    manifest={'asset_id':accepted['id'],'draft_ref':snap['draft_ref'],'content_hash':snap['content_hash'],'page_count':len(files),'pages':[{'file':name,'sha256':hashlib.sha256(raw).hexdigest(),'page_number':i+1} for i,(name,raw) in enumerate(files)]}
    with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as archive:
        for name,raw in files:archive.writestr(name,raw)
        archive.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))
    with store.connect() as db:
        latest=store._get(db,run_id,owner);_snapshot(latest,data);current=_load(db,latest,snap)
        require(current is not None and current['revision']==state['revision'],'VERSION_CONFLICT','导出期间海报发生变化，请重新导出')
    return stream.getvalue(),'application/zip','youji-poster-history.zip'


def generate(store,owner,run_id,data):
    """Local composition only. Reserve once, render outside SQL, then atomically CAS."""
    require(isinstance(data,dict) and set(data)<={'draft_ref','content_hash','expected_revision','idempotency_key','brief','source_image','style'},'INVALID_INPUT','海报生成请求无效')
    key=data.get('idempotency_key'); brief=data.get('brief',''); style=data.get('style','zine')
    require(isinstance(key,str) and 1<=len(key)<=128,'INVALID_INPUT','请提供幂等键')
    require(type(data.get('expected_revision')) is int,'INVALID_INPUT','请提供当前版本')
    require(isinstance(brief,str) and len(brief)<=4000,'INVALID_INPUT','海报说明不得超过4000字')
    require(isinstance(style,str) and style in ('zine','editorial','minimal'),'INVALID_INPUT','海报风格无效')
    fingerprint=digest({'run_id':run_id,'data':data})
    with store.connect() as db:
        run=store._get(db,run_id,owner); _snapshot(run,data)
    source=normalize_image(data.get('source_image'))['data_url']
    call_id=uuid4().hex
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        run=store._get(db,run_id,owner); snap=_snapshot(run,data)
        replay=db.execute('SELECT input_hash,status,result,error FROM poster_generation_calls WHERE owner=? AND key=?',(owner,key)).fetchone()
        if replay:
            require(replay[0]==fingerprint,'IDEMPOTENCY_CONFLICT','幂等键已用于其他生成要求')
            if replay[1]=='SUCCEEDED': return _public(db,run,json.loads(replay[2]))
            require(False,'INVALID_TRANSITION','本次生成仍在进行或已失败，未重复生成；请查看当前海报后重新发起')
        state=_load(db,run,snap)
        require(state is not None and state['revision']==data['expected_revision'],'VERSION_CONFLICT','海报已变化，请刷新后生成')
        db.execute('INSERT INTO poster_generation_calls(id,owner,run_id,key,input_hash,status,started) VALUES(?,?,?,?,?,?,?)',(call_id,owner,run_id,key,fingerprint,'RUNNING',time.time()))
    try:
        from backend import poster_local
        image=poster_local.render(source,snap,brief,style)
        return mutate(store,owner,run_id,{'action':'import','draft_ref':data['draft_ref'],'content_hash':data['content_hash'],'expected_revision':data['expected_revision'],'idempotency_key':'generation:'+call_id,'image':image,'brief':brief,'prompt':'本机确定性排版；保留实拍主体，纸张质感、衬线标题与档案标注。'},_generation={'id':call_id,'skill_version':'gc-minimal-zine-poster-local-v1','style':style})
    except Exception as exc:
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute("UPDATE poster_generation_calls SET status='FAILED',error=?,finished=? WHERE id=? AND owner=? AND status='RUNNING'",(exc.code if isinstance(exc,DomainError) else 'LOCAL_RENDER_FAILED',time.time(),call_id,owner))
        if isinstance(exc,DomainError): raise
        raise DomainError('INVALID_TRANSITION','本机海报生成失败，原版本已保留') from exc
