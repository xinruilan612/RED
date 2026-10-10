"""Owner-scoped BYOK connections, immutable route identity and explicit paid probes."""
import json
import math
import re
import time
from uuid import uuid4
from urllib.parse import urlsplit, urlunsplit
from backend.contracts import DomainError, require
from backend.credentials import CredentialVault

CATALOG = [
    ('deepseek','DeepSeek','https://api.deepseek.com','openai','https://api-docs.deepseek.com/'),
    ('qwen','通义千问','https://dashscope.aliyuncs.com/compatible-mode/v1','openai','https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope'),
    ('kimi','Kimi','https://api.moonshot.cn/v1','openai','https://platform.kimi.com/docs/api/overview'),
    ('doubao','豆包 / 火山方舟','https://ark.cn-beijing.volces.com/api/v3','openai','https://docs.volcengine.com/docs/ark/compatible-with-openai-sdk'),
    ('openai','OpenAI','https://api.openai.com/v1','openai','https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create'),
    ('openai_responses','OpenAI Responses','https://api.openai.com/v1','responses','https://developers.openai.com/api/docs/guides/migrate-to-responses'),
    ('zhipu','智谱 GLM','https://open.bigmodel.cn/api/paas/v4','openai','https://docs.bigmodel.cn/cn/guide/develop/openai/introduction'),
    ('minimax','MiniMax','https://api.minimax.cn/v1','openai','https://platform.minimax.cn/docs/api-reference/text-openai-api'),
    ('wenxin','百度文心','https://qianfan.baidubce.com/v2','openai','https://ai.baidu.com/ai-doc/WENXINWORKSHOP/0m2vwrjws'),
    ('hunyuan','腾讯混元','https://api.hunyuan.cloud.tencent.com/v1','openai','https://cloud.tencent.cn/document/product/1729/111007'),
    ('anthropic','Claude','https://api.anthropic.com/v1','anthropic','https://platform.claude.com/docs/en/api/messages'),
    ('gemini','Gemini','https://generativelanguage.googleapis.com/v1beta/openai','openai','https://ai.google.dev/gemini-api/docs/openai'),
    ('custom','自定义 / 网关','','openai',''),
]
PROVIDERS={row[0]:dict(zip(('id','name','base_url','protocol','docs'),row)) for row in CATALOG}
# Documentation examples checked 2026-10-10, not a remote availability inventory.
MODEL_SUGGESTIONS={
    'deepseek':['deepseek-flash','deepseek-v4-pro'],
    'qwen':['qwen-plus','qwen-max','qwen-turbo'],
    'kimi':['kimi-k2.6','kimi-k3'],
    'openai':['gpt-4.1-mini'],'openai_responses':['gpt-4.1-mini'],
    'minimax':['MiniMax-M2.7','MiniMax-M2.5'],
    'anthropic':['claude-sonnet-5-5','claude-haiku-5-5'],
    'gemini':['gemini-3.8-flash'],
}
for provider_id,entry in PROVIDERS.items():entry['models']=MODEL_SUGGESTIONS.get(provider_id,[])
PROTOCOLS={'openai':'OpenAI Chat Completions','responses':'OpenAI Responses','anthropic':'Anthropic Messages'}
# Local budget estimates, not advertised vendor prices or a supplier spending cap.
CONNECTION_DEFAULTS={'rate_usd_per_million':20.0,'run_budget_usd':1.0,'day_budget_usd':5.0}
ENDPOINTS={'openai':'/chat/completions','responses':'/responses','anthropic':'/messages'}


def endpoint_protocol(value):
    if not isinstance(value,str):return None
    try:path=urlsplit(value.strip()).path.rstrip('/')
    except ValueError:return None
    return next((name for name,suffix in ENDPOINTS.items() if path.endswith(suffix)),None)


def base_url(value, protocol=None):
    require(isinstance(value,str) and 0<len(value)<=500,'INVALID_INPUT','请输入模型服务 Base URL')
    value=value.strip()
    try:p=urlsplit(value)
    except ValueError:raise DomainError('INVALID_INPUT','模型地址无效') from None
    require(p.scheme=='https' and p.hostname and not p.username and not p.password and not p.query and not p.fragment and not any(c.isspace() for c in value) and '\\' not in value,'INVALID_INPUT','模型地址必须是 HTTPS 且不能包含账号、查询参数或片段')
    try:require(p.port in (None,443),'INVALID_INPUT','模型地址只允许 HTTPS 443 端口')
    except ValueError:raise DomainError('INVALID_INPUT','模型端口无效') from None
    import ipaddress
    try:address=ipaddress.ip_address(p.hostname)
    except ValueError:require('.' in p.hostname and p.hostname.lower()!='localhost','INVALID_INPUT','模型地址必须使用公网主机')
    else:require(address.is_global,'INVALID_INPUT','模型地址不能指向内网')
    detected=endpoint_protocol(value)
    require(protocol is None or protocol in PROTOCOLS,'INVALID_INPUT','模型接口协议无效')
    require(not detected or not protocol or detected==protocol,'INVALID_INPUT','完整接口地址与所选协议不一致，请在高级设置中选择对应协议')
    path=p.path.rstrip('/')
    if detected:path=path[:-len(ENDPOINTS[detected])]
    # Only recognized official hosts get their documented root prefix. Custom
    # gateway paths remain exactly what the owner supplied; never guess /v1.
    if not path and not detected:
        for preset in PROVIDERS.values():
            candidate=urlsplit(preset['base_url'])
            if candidate.hostname==p.hostname and (not protocol or preset['protocol']==protocol):
                path=candidate.path.rstrip('/')
                break
    return urlunsplit(('https',p.netloc.lower(),path,'',''))


class ModelConnections:
    def __init__(self,store,config,vault=None):
        self.store,self.config=store,config
        self.vault=vault or CredentialVault(store)

    def _get(self,owner,connection_id,db=None):
        if db is None:
            with self.store.connect() as connection:return self._get(owner,connection_id,connection)
        row=db.execute('SELECT payload,secret,version,active FROM model_connections WHERE owner=? AND id=?',(owner,connection_id)).fetchone()
        require(row and row[3],'NOT_FOUND','模型连接不存在或已撤销')
        return json.loads(row[0]),row[1],row[2]

    def default_id(self,owner):
        with self.store.connect() as db:
            row=db.execute('SELECT connection_id FROM model_preferences WHERE owner=?',(owner,)).fetchone()
        return row[0] if row else None

    def public(self,owner):
        with self.store.connect() as db:
            rows=db.execute('SELECT payload FROM model_connections WHERE owner=? AND active=1 ORDER BY id',(owner,)).fetchall()
        default=self.default_id(owner)
        return {'catalog':list(PROVIDERS.values()),'protocols':PROTOCOLS,'defaults':CONNECTION_DEFAULTS,
                'connections':[json.loads(r[0]) for r in rows],
                'default_connection_id':default,'platform':self.config.public(),'ready':any(json.loads(r[0])['id']==default for r in rows) if default else self.config.ready}

    def effective_public(self,owner):
        result={**self.config.public(),'billing_source':'platform'}
        selected=self.default_id(owner)
        if not selected:return result
        try:item,_,_=self._get(owner,selected)
        except DomainError:
            return {**result,'ready':False,'provider':'已撤销的个人连接','model':'','billing_source':'user','message':'默认连接已撤销，请明确选择其他连接或平台 DeepSeek'}
        return {**result,'ready':True,'provider':PROVIDERS[item['provider']]['name'],'model':item['model'],
                'run_budget_usd':item['run_budget_usd'],'day_budget_usd':item['day_budget_usd'],
                'billing_source':'user','message':'使用你的 API Key；费用由对应厂商收取，未测试的连接请先测试'}

    def save(self,owner,data):
        require(isinstance(data,dict) and set(data)<={'id','version','label','provider','model','base_url','api_key','protocol','json_mode','rate_usd_per_million','run_budget_usd','day_budget_usd'},'INVALID_INPUT','模型连接字段无效')
        require({'provider','model'}<=set(data),'INVALID_INPUT','请选择厂商并填写模型 ID')
        provider=data['provider'];require(isinstance(provider,str) and provider in PROVIDERS,'INVALID_INPUT','模型厂商无效')
        model=data['model'].strip() if isinstance(data['model'],str) else data['model'];require(isinstance(model,str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,159}',model),'INVALID_INPUT','请输入厂商控制台的模型 ID')
        label=data.get('label') or PROVIDERS[provider]['name'];require(isinstance(label,str) and 1<=len(label)<=80,'INVALID_INPUT','连接名称最多80字')
        raw_url=data.get('base_url') or PROVIDERS[provider]['base_url']
        detected=endpoint_protocol(raw_url)
        secret=None
        if 'api_key' in data:
            key=data['api_key'].strip() if isinstance(data['api_key'],str) else data['api_key'];require(isinstance(key,str) and 4<=len(key)<=4096 and not any(c.isspace() for c in key),'INVALID_INPUT','API Key 格式无效')
            secret=self.vault.encrypt(key)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            previous={}
            if data.get('id'):
                previous,old_secret,version=self._get(owner,data['id'],db)
                require(data.get('version')==version,'VERSION_CONFLICT','连接已更新，请刷新')
                connection_id=data['id'];version+=1
            else:
                require(secret is not None,'INVALID_INPUT','新连接需要 API Key')
                require(db.execute('SELECT COUNT(*) FROM model_connections WHERE owner=? AND active=1',(owner,)).fetchone()[0]<30,'INVALID_INPUT','最多保存30个模型连接')
                connection_id=str(uuid4());version=1
            protocol=data.get('protocol') or detected or (previous.get('protocol') if previous.get('provider')==provider else None) or PROVIDERS[provider]['protocol']
            require(isinstance(protocol,str) and protocol in PROTOCOLS,'INVALID_INPUT','模型接口协议无效')
            url=base_url(raw_url,protocol)
            if previous:
                require(secret is not None or (previous['provider']==provider and previous['base_url']==url),'INVALID_INPUT','更换厂商或服务地址时请重新填写 API Key')
                secret=secret or old_secret
            fees={name:data.get(name,previous.get(name,default)) for name,default in CONNECTION_DEFAULTS.items()}
            for value in fees.values():
                require(type(value) in (float,int) and math.isfinite(value) and 0<value<=10000,'INVALID_INPUT','费率和预算必须是 0 至 10000 之间的正数')
            require(fees['day_budget_usd']>=fees['run_budget_usd'],'INVALID_INPUT','每日预算不能小于单任务预算')
            json_mode=data.get('json_mode',previous.get('json_mode',False))
            require(type(json_mode) is bool,'INVALID_INPUT','JSON 模式设置无效')
            require(not json_mode or protocol!='anthropic','INVALID_INPUT','Anthropic Messages 使用提示词输出 JSON，请关闭强制 JSON 模式')
            payload={'id':connection_id,'version':version,'label':label,'provider':provider,'model':model,'base_url':url,
                     'protocol':protocol,'json_mode':json_mode,**fees,'test_status':'untested','last_tested':None}
            db.execute('INSERT INTO model_connections(owner,id,version,payload,secret,active) VALUES(?,?,?,?,?,1) ON CONFLICT(owner,id) DO UPDATE SET version=excluded.version,payload=excluded.payload,secret=excluded.secret',(owner,connection_id,version,json.dumps(payload),secret))
        return payload

    def select(self,owner,data):
        require(isinstance(data,dict) and set(data)=={'connection_id'},'INVALID_INPUT','默认模型字段无效')
        connection_id=data['connection_id'];require(connection_id is None or isinstance(connection_id,str),'INVALID_INPUT','连接 ID 无效')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if connection_id:self._get(owner,connection_id,db)
            db.execute('INSERT INTO model_preferences VALUES(?,?) ON CONFLICT(owner) DO UPDATE SET connection_id=excluded.connection_id',(owner,connection_id))
        return self.public(owner)

    def delete(self,owner,connection_id,data):
        require(isinstance(data,dict) and set(data)=={'version'},'INVALID_INPUT','撤销模型连接需提供版本')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');_,_,version=self._get(owner,connection_id,db)
            require(data['version']==version,'VERSION_CONFLICT','连接已更新，请刷新')
            db.execute("UPDATE model_connections SET active=0,secret='' WHERE owner=? AND id=?",(owner,connection_id))
            # Keep the selected ID: deleting a default must not silently switch billing to platform.
        return self.public(owner)

    def route(self,owner,connection_id=None):
        from backend.model_router import Route
        selected=connection_id if connection_id is not None else self.default_id(owner)
        if not selected:return None
        item,_,version=self._get(owner,selected)
        return Route(item['provider'],item['model'],item['rate_usd_per_million']/1_000_000,
                     connection_id=selected,connection_version=version,owner_id=owner,billing_source='user',
                     run_budget_usd=item['run_budget_usd'],day_budget_usd=item['day_budget_usd'])

    def adapter(self,route,owner):
        require(route.billing_source=='user','CONFIG_INVALID','个人模型计费来源无效')
        require(route.owner_id==owner,'FORBIDDEN','模型连接不属于当前用户')
        item,secret,version=self._get(owner,route.connection_id)
        require(version==route.connection_version and item['provider']==route.provider and item['model']==route.model and item['rate_usd_per_million']/1_000_000==route.rate and item['run_budget_usd']==route.run_budget_usd and item['day_budget_usd']==route.day_budget_usd,'CONFIG_INVALID','模型连接已修改，请新建任务以使用新版本')
        from backend.provider import ConnectedModel
        return ConnectedModel(item,self.vault.decrypt(secret))

    def test(self,owner,connection_id,data):
        require(isinstance(data,dict) and set(data)=={'version','acknowledge_cost'} and data['acknowledge_cost'] is True,'INVALID_INPUT','请确认连接测试会产生少量模型费用')
        route=self.route(owner,connection_id);require(route.connection_version==data['version'],'VERSION_CONFLICT','连接已更新，请刷新')
        now=time.time();test_id=str(uuid4())
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            require(not db.execute('SELECT 1 FROM model_connection_tests WHERE owner=? AND started>?',(owner,now-10)).fetchone(),'RATE_LIMITED','请等待10秒后再测试')
            used=db.execute('SELECT COALESCE(SUM(COALESCE(tokens,reserved)*rate),0) FROM model_connection_tests WHERE owner=? AND started>?',(owner,now-86400)).fetchone()[0]
            if db.has_table('live_calls'):
                used+=db.execute("SELECT COALESCE(SUM(COALESCE(c.actual,c.reserved)*a.rate),0) FROM live_calls c JOIN model_audit a ON a.call_id=c.id WHERE a.billing_source='user' AND a.billing_owner=? AND a.started>?",(owner,now-86400)).fetchone()[0]
            require(used+512*route.rate<=route.day_budget_usd,'BUDGET_EXCEEDED','连接测试费用预留超过每日预算')
            db.execute("INSERT INTO model_connection_tests(id,owner,connection_id,started,reserved,rate,status) VALUES(?,?,?,?,512,?,'calling')",(test_id,owner,connection_id,now,route.rate))
        try:
            value,tokens,_=self.adapter(route,owner).complete_result([{'role':'system','content':'Return only valid JSON: {"ok":true}'},{'role':'user','content':'JSON connection test'}],max_tokens=128)
            require(type(tokens) is int and 0<=tokens<=512,'MODEL_OUTPUT_INVALID','测试用量报告超出预留，保留费用预留')
            require(value.get('ok') is True,'MODEL_OUTPUT_INVALID','接口已响应，但未通过 JSON 输出测试')
        except Exception as error:
            with self.store.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                db.execute("UPDATE model_connection_tests SET status='failed' WHERE id=?",(test_id,))
                # Report the failure only on the tested version. A concurrent edit
                # or deletion must not be overwritten by an old probe's result.
                row=db.execute('SELECT payload,version,active FROM model_connections WHERE owner=? AND id=?',(owner,connection_id)).fetchone()
                if row and row[2] and row[1]==route.connection_version:
                    item=json.loads(row[0]);item.update(test_status='failed',last_tested=now)
                    db.execute('UPDATE model_connections SET payload=? WHERE owner=? AND id=?',(json.dumps(item),owner,connection_id))
            if isinstance(error,DomainError):raise
            raise DomainError('PROVIDER_ERROR','模型连接测试失败；用量未知，未自动重试') from None
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');db.execute("UPDATE model_connection_tests SET tokens=?,status='passed' WHERE id=?",(tokens,test_id))
            item,_,version=self._get(owner,connection_id,db)
            require(version==route.connection_version,'VERSION_CONFLICT','测试期间连接已修改，请重试')
            item.update(test_status='passed',last_tested=now)
            db.execute('UPDATE model_connections SET payload=? WHERE owner=? AND id=?',(json.dumps(item),owner,connection_id))
        return {'status':'passed','tokens':tokens,'provider':route.provider,'model':route.model,'tested_at':now}
