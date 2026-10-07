"""Account-scoped editable multimodal adapter, independent of benchmark weights."""
import copy
import hashlib
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

def history_rows(state,account,config):
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
    return rows[:100]

class Topics:
    def __init__(self,operations,encoder=None): self.operations=operations;self.encoder=encoder
    def encode(self,texts,images):
        if self.encoder: return self.encoder(texts,images)
        from backend.topic_encoder import encode
        return encode(texts,images)
    def current(self,owner,identity,version=None):
        state=self.operations.read(owner);account=find_account(state,identity)
        require(not account.get('demo_sample'),'INVALID_INPUT','请切换到自己的账号；演示作品不参与真实选题评估')
        if version is not None: require(type(version) is int and state['version']==version,'VERSION_CONFLICT','账号或数据已更新，请刷新后重新比较')
        return state,account
    def read(self,owner,identity):
        state,account=self.current(owner,identity);config=config_for(state,account);rows=history_rows(state,account,config)
        from backend.topic_encoder import availability
        return dict(profile=account['profile'],account_revision=account['revision'],version=state['version'],config=config,history=[{k:r[k] for k in ('id','title','has_image','eligible','exclusion')} for r in rows],encoder_ready=bool(self.encoder) or availability()['ready'])
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
        public_samples=copy.deepcopy(state.get('public_topic_samples',{}).get(account['id'],[])[-100:])
        texts=[config['positioning']+'。目标受众：'+config['audience']]+[r['title']+'。'+r['body'] for r in candidates]+[r['title']+'。'+r['body'] for r in history]+[r['title']+'。'+r.get('body','') for r in public_samples]
        encoded=self.encode(texts,images)
        for i,row in enumerate(candidates):
            row['text_vector']=encoded['text_vectors'][i+1];row['image_vector']=encoded['image_vectors'][ix[i]] if i in ix else None
        for i,row in enumerate(history): row['text_vector']=encoded['text_vectors'][1+len(candidates)+i]
        from backend.topic_ranking import evaluate
        result=evaluate(encoded['text_vectors'][0],candidates,history,config)
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
