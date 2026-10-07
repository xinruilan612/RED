"""Account-scoped editable multimodal adapter, independent of benchmark weights."""
import copy
import hashlib
import json
import math
from datetime import datetime, timezone
from uuid import uuid4
from backend.accounts import find_account, save_account
from backend.analytics import window_quality, latest_metrics, parsed
from backend.contracts import require
from backend.demo import validate_text

DEFAULTS=dict(text_weight=.55,image_weight=.25,profile_weight=.2,neighbors=5,window='72h',metric='views')

def validate_config(config):
    require(isinstance(config,dict) and set(config)==set(DEFAULTS)|{'positioning','audience'},'INVALID_INPUT','请完整填写选题设置')
    result={k:validate_text(config[k],k,800,True) for k in ('positioning','audience')}
    for k in ('text_weight','image_weight','profile_weight'):
        v=config[k]
        require(type(v) in (int,float) and math.isfinite(v) and 0<=v<=1,'INVALID_INPUT','参考权重须在 0 至 1 之间')
        result[k]=v
    require(sum(result[k] for k in ('text_weight','image_weight','profile_weight'))>0,'INVALID_INPUT','至少保留一项参考权重')
    require(type(config['neighbors']) is int and 1<=config['neighbors']<=10,'INVALID_INPUT','参考作品数须为 1 至 10')
    require(config['window'] in ('24h','72h') and config['metric'] in ('views','likes','saves','comments'),'INVALID_INPUT','观察时长或指标无效')
    result.update({k:config[k] for k in ('neighbors','window','metric')})
    return result

def apply_topic_action(state,action,data):
    account=find_account(state,data.get('account_id'))
    if action=='topic_config':
        require(set(data)=={'account_id','config'},'INVALID_INPUT','设置字段无效')
        config=validate_config(data['config'])
        profile=copy.deepcopy(account['profile'])
        profile.update(positioning=config.pop('positioning'),audience=config.pop('audience'))
        save_account(state,dict(id=account['id'],name=account['name'],platform=account['platform'],profile=profile))
        state.setdefault('topic_settings',{})[account['id']]=config
        state.setdefault('topic_results',{}).pop(account['id'],None)
    elif action=='topic_image':
        require(set(data)=={'account_id','publication_id','encoded'},'INVALID_INPUT','封面字段无效')
        require(any(p['id']==data['publication_id'] and p.get('account_id')==account['id'] and p.get('provenance')=='manual' for p in state['publications']),'RESOURCE_NOT_FOUND','作品不可访问')
        state.setdefault('topic_images',{})[data['publication_id']]=data['encoded']
        state.setdefault('topic_results',{}).pop(account['id'],None)
    elif action=='topic_result':
        require(set(data)=={'account_id','result'},'INVALID_INPUT','结果字段无效')
        state.setdefault('topic_results',{})[account['id']]=data['result']

def config_for(state,account):
    return {**DEFAULTS,**state.get('topic_settings',{}).get(account['id'],{}),'positioning':account['profile'].get('positioning',''),'audience':account['profile'].get('audience','')}

def training_history_digest(state,account,config):
    """Stable model invalidation; prediction saves do not change this snapshot."""
    posts=sorted([p for p in state['publications'] if p.get('account_id')==account['id'] and p.get('provenance')=='manual'],key=lambda p:p['id'])
    ids={p['id'] for p in posts}
    metrics=sorted([m for m in state['metrics'] if m.get('publication_id') in ids],key=lambda m:json.dumps(m,sort_keys=True))
    images={key:value for key,value in state.get('topic_images',{}).items() if key in ids}
    payload=dict(posts=posts,metrics=metrics,images=images,profile={k:config[k] for k in ('positioning','audience','metric','window')})
    return hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()

def history_rows(state,account,config,limit=100):
    latest=latest_metrics(state); rows=[]; now=datetime.now(timezone.utc)
    for post in state['publications']:
        if post.get('account_id')!=account['id'] or post.get('platform')!=account['platform'] or post.get('provenance')!='manual' or not post.get('published_at'): continue
        if parsed(post['published_at'])>now: continue
        metric=latest.get((post['id'],config['window'])); reason='';value=None;observed=None
        if post.get('format')!='image_text': reason='目前只比较图文作品'
        elif post.get('traffic')!='organic': reason='请在作品记录中确认是否为自然流量'
        elif not metric or metric.get('source_type')!='manual': reason='尚未记录此观察时长的数据'
        elif parsed(metric['observed_at'])>now: reason='观察时间不能在未来'
        elif window_quality(post,metric)[0]!='comparable': reason='实际观察时长与所选窗口不一致'
        else:
            candidate=metric.get('values',{}).get(config['metric'])
            if type(candidate) not in (int,float) or not math.isfinite(candidate) or candidate<0: reason='尚未记录所选指标'
            else: value=candidate;observed=metric['observed_at']
        image=state.get('topic_images',{}).get(post['id'])
        from backend.topic_encoder import MODEL_NAME
        if image and image.get('model') != MODEL_NAME: image=None
        rows.append(dict(id=post['id'],title=post['content']['selected_title'],body=post['content'].get('body',''),published_at=post['published_at'],observed_at=observed,value=value,eligible=value is not None,exclusion=reason,has_image=bool(image),image_vector=image.get('vector') if image else None))
    rows.sort(key=lambda r:parsed(r['published_at']),reverse=True)
    return rows[:limit] if limit is not None else rows

class Topics:
    def __init__(self,operations,encoder=None): self.operations=operations;self.encoder=encoder
    def encode(self,texts,images):
        from backend.topic_encoder import encode
        engine=self.encoder or encode
        if len(texts)<=128 and all(len(t)<=10000 for t in texts):
            return engine(texts,images)
        # Preserve long public articles and both pools without exceeding the
        # isolated encoder's per-call bounds. Never silently drop the tail.
        chunks=[];groups=[]
        for text in texts:
            indexes=[]
            for start in range(0,len(text),9000):
                part=text[start:start+9000]
                if part.strip(): indexes.append((len(chunks),len(part)));chunks.append(part)
            require(bool(indexes),'INVALID_INPUT','参考正文不能为空')
            groups.append(indexes)
        vectors=[];image_vectors=[];model=None
        for start in range(0,len(chunks),128):
            result=engine(chunks[start:start+128],images if start==0 else [])
            if model is not None: require(model==result['model'],'INVALID_INPUT','图文编码模型不一致，请重新比较')
            model=result['model'];vectors.extend(result['text_vectors'])
            if start==0: image_vectors=result['image_vectors']
        pooled=[]
        for group in groups:
            values=[sum(vectors[i][axis]*weight for i,weight in group) for axis in range(len(vectors[group[0][0]]))]
            norm=math.sqrt(sum(v*v for v in values))
            require(norm>0,'INVALID_INPUT','参考正文无法编码，请检查内容')
            pooled.append([v/norm for v in values])
        return dict(model=model,text_vectors=pooled,image_vectors=image_vectors)
    def current(self,owner,identity,version=None):
        state=self.operations.read(owner);account=find_account(state,identity)
        require(not account.get('demo_sample'),'INVALID_INPUT','请切换到自己的账号；演示作品不参与真实选题评估')
        if version is not None: require(type(version) is int and state['version']==version,'VERSION_CONFLICT','账号或数据已更新，请刷新后重新比较')
        return state,account
    def read(self,owner,identity):
        state,account=self.current(owner,identity);config=config_for(state,account);rows=history_rows(state,account,config)
        from backend.topic_encoder import availability
        from backend.skapp_personal import availability as skapp_availability
        return dict(skapp=skapp_availability(owner,identity,dict(config,platform=account['platform'])),profile=account['profile'],account_revision=account['revision'],version=state['version'],config=config,history=[{k:r[k] for k in ('id','title','has_image','eligible','exclusion')} for r in rows],encoder_ready=bool(self.encoder) or availability()['ready'])
    def save(self,owner,data):
        require(set(data)=={'account_id','version','config'},'INVALID_INPUT','设置参数无效')
        self.current(owner,data['account_id'],data['version']);validate_config(data['config'])
        self.operations.command(owner,dict(action='topic_config',payload=dict(account_id=data['account_id'],config=data['config']),version=data['version'],key=str(uuid4())))
        return self.read(owner,data['account_id'])
    def image(self,owner,data):
        require(set(data)=={'account_id','version','publication_id','image'},'INVALID_INPUT','封面参数无效')
        state,account=self.current(owner,data['account_id'],data['version'])
        require(any(p['id']==data['publication_id'] and p.get('account_id')==account['id'] and p.get('provenance')=='manual' for p in state['publications']),'RESOURCE_NOT_FOUND','作品不可访问')
        require(isinstance(data['image'],str) and len(data['image'])<=4_200_000,'INVALID_INPUT','请使用 3 MB 以内的图片')
        encoded=self.encode([], [data['image']])
        value=dict(vector=encoded['image_vectors'][0],model=encoded['model'],hash=hashlib.sha256(data['image'].encode()).hexdigest())
        self.operations.command(owner,dict(action='topic_image',payload=dict(account_id=data['account_id'],publication_id=data['publication_id'],encoded=value),version=data['version'],key=str(uuid4())),internal=True)
        return self.read(owner,data['account_id'])
    def training_data(self,owner,data):
        """Export only this owner's compatible manual history, never public counts."""
        require(set(data)=={'account_id','version'},'INVALID_INPUT','训练数据参数无效')
        state,account=self.current(owner,data['account_id'],data['version'])
        config=config_for(state,account)
        history=history_rows(state,account,config,limit=None)
        require(len(history)<=10000,'INVALID_INPUT','历史过多，请分批整理训练数据')
        eligible=[];excluded=[]
        hours=int(config['window'][:-1])
        posts={p['id']:p for p in state['publications']}
        for row in history:
            reason=row['exclusion']
            if not reason and not row['has_image']: reason='缺少真实封面特征'
            if not reason:
                elapsed=(parsed(row['observed_at'])-parsed(row['published_at'])).total_seconds()/3600
                if abs(elapsed-hours)>hours*.05: reason='实际观测时长不在训练窗口的±5%以内'
            url=posts[row['id']].get('url','')
            if not reason and not url.startswith(('https://','http://')): reason='缺少作品来源链接'
            if reason: excluded.append({'id':row['id'],'reason':reason})
            else: eligible.append(row)
        from backend.topic_encoder import MODEL_NAME
        from backend.skapp_personal import scope_digest
        records=[]
        for start in range(0,len(eligible),128):
            batch=eligible[start:start+128]
            encoded=self.encode([r['title']+'。'+r['body'] for r in batch],[])
            require(encoded['model']==MODEL_NAME,'INVALID_INPUT','训练数据编码器不兼容')
            for row,vector in zip(batch,encoded['text_vectors']):
                records.append(dict(id=row['id'],published_at=row['published_at'],observed_at=row['observed_at'],value=row['value'],visual=row['image_vector'],textual=vector,source_url=posts[row['id']]['url']))
        self.current(owner,data['account_id'],data['version'])
        return dict(schema_version=1,training_history_digest=training_history_digest(state,account,config),scope_digest=scope_digest(owner,account['id']),encoder_id=MODEL_NAME,target_metric=config['metric'],window_hours=hours,records=records,excluded=excluded,provenance='manual_reported_not_platform_verified',minimum_training_records=100)

    def evaluate(self,owner,data):
        require(set(data)=={'account_id','version','candidates'},'INVALID_INPUT','比较参数无效')
        state,account=self.current(owner,data['account_id'],data['version']);config=config_for(state,account)
        require(bool(config['positioning'].strip()),'INVALID_INPUT','先写一句你的账号定位，再比较选题')
        incoming=data['candidates']; require(isinstance(incoming,list) and 1<=len(incoming)<=5,'INVALID_INPUT','每次比较 1 至 5 个选题')
        candidates=[];images=[];ix={}
        for row in incoming:
            require(isinstance(row,dict) and set(row)<={'id','title','body','image'} and {'id','title'}<=set(row),'INVALID_INPUT','选题字段无效')
            c=dict(id=validate_text(row['id'],'选题标识',100),title=validate_text(row['title'],'选题标题',200),body=validate_text(row.get('body',''),'选题内容',6000,True))
            require(isinstance(row.get('image',''),str),'INVALID_INPUT','图片格式无效')
            if row.get('image'):
                require(len(row['image'])<=4_200_000,'INVALID_INPUT','图片须小于 3 MB')
                ix[len(candidates)]=len(images);images.append(row['image'])
            candidates.append(c)
        require(len({c['id'] for c in candidates})==len(candidates),'INVALID_INPUT','选题标识不能重复')
        history=history_rows(state,account,config)
        from backend.public_topics import scoped_samples
        public_samples=scoped_samples(state,account)[-100:]
        texts=[config['positioning']+'。目标受众：'+config['audience']]+[r['title']+'。'+r['body'] for r in candidates]+[r['title']+'。'+r['body'] for r in history]+[r['title']+'。'+r.get('body','') for r in public_samples]
        encoded=self.encode(texts,images)
        for i,row in enumerate(candidates):
            row['text_vector']=encoded['text_vectors'][i+1];row['image_vector']=encoded['image_vectors'][ix[i]] if i in ix else None
        for i,row in enumerate(history): row['text_vector']=encoded['text_vectors'][1+len(candidates)+i]
        from backend.topic_ranking import evaluate
        # Legacy matching remains useful, but its kernel estimates are not SKAPP.
        result=evaluate(encoded['text_vectors'][0],candidates,history,config)
        from backend.skapp_personal import predict as skapp_predict
        skapp=skapp_predict(owner,account['id'],dict(config,platform=account['platform']),candidates,encoded['model'],profile_vector=encoded['text_vectors'][0])
        predictions={r['id']:r for r in skapp.get('predictions',[])} if skapp.get('available') else {}
        result.update(skapp=skapp,method='upstream_skapp_shared' if predictions else 'reference_matching_only',status='experimental_prediction' if predictions else 'matching_only')
        result['validation']={'history_count':len(history),'eligible_count':sum(r['eligible'] for r in history),'gate':bool(predictions),'reason':skapp.get('message',''),'model_validation':skapp.get('validation')}
        for row in result['candidates']:
            row['estimated_value']=predictions.get(row['id'],{}).get('predicted_value')
            row['reason']=skapp.get('message','')
            for ref in row.get('references',[]):
                ref.pop('contribution',None);ref.pop('contribution_observations',None)
        result['candidates'].sort(key=lambda r:(r['estimated_value'] is None,-(r['estimated_value'] or 0),-r['fit_score'],r['id']))
        from backend.public_topic_ranking import rank_public
        offset=1+len(candidates)+len(history)
        for i,row in enumerate(public_samples): row['text_vector']=encoded['text_vectors'][offset+i]
        public=rank_public(encoded['text_vectors'][0],candidates,public_samples,config)
        refs={r['id']:r for r in public['candidates']}
        for row in result['candidates']:
            row.update({k:v for k,v in refs[row['id']].items() if k!='id'})
        result.update(public_sample_count=public['public_sample_count'],public_method=public['method'],public_evidence_boundary=public['evidence_boundary'],public_prediction_available=False)
        self.current(owner,data['account_id'],data['version'])
        result.update(config=config,profile_revision=account['revision'],account_id=account['id'],encoder=encoded['model'],created_at=datetime.now(timezone.utc).isoformat(),source='user_reported_history',history_limit=100,data_version=data['version'])
        self.operations.command(owner,dict(action='topic_result',payload=dict(account_id=account['id'],result=result),version=data['version'],key=str(uuid4())),internal=True)
        result['version']=data['version']+1
        return result
