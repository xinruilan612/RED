"""DeepSeek text adapter. Secrets never enter Run, HTTP responses or error strings."""
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPRedirectHandler

from backend.contracts import DomainError, require, PARAMETERS

ROOT = Path(__file__).resolve().parents[1]
MODEL = 'deepseek-flash'
# Conservative all-token rate: peak output USD / 1M, checked 2026-09-20.
RATE = 1.2 / 1_000_000


@dataclass(frozen=True)
class Config:
    api_key: str = field(default='', repr=False)
    model: str = MODEL
    run_budget_usd: float = 0.10
    day_budget_usd: float = 0.50
    routes: dict = field(default_factory=dict)

    @property
    def ready(self):
        return bool(self.api_key.strip())

    def public(self):
        return {'ready':self.ready, 'provider':'DeepSeek', 'model':self.model,
                'run_budget_usd':self.run_budget_usd, 'day_budget_usd':self.day_budget_usd,
                'run_tokens_max':PARAMETERS['run_tokens_max'],'run_attempts_max':PARAMETERS['run_attempts_max'],
                'message':'已配置，可新建真实 AI 创作' if self.ready else '请在项目根目录 .env 填写 DEEPSEEK_API_KEY，然后重启服务'}


def load_config(path=None, environ=None):
    """Simple literal dotenv parser, no shell execution/interpolation, no printing values."""
    values={}
    path=Path(path) if path is not None else ROOT/'.env'
    if path.exists():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            line=line.strip()
            if not line or line.startswith('#'): continue
            require('=' in line, 'CONFIG_INVALID', '.env 格式错误，请使用 KEY=值')
            key,value=line.split('=',1); value=value.strip()
            if len(value)>=2 and value[0]==value[-1] and value[0] in "\"'":value=value[1:-1]
            values[key.strip()]=value
    values.update(os.environ if environ is None else environ)
    key=values.get('DEEPSEEK_API_KEY','').strip()
    require(not any(c.isspace() for c in key), 'CONFIG_INVALID', 'API Key 中不能有空格或换行')
    try:
        routes=json.loads(values.get('MODEL_ROUTES_JSON','{}'))
        from backend.model_router import STAGES
        require(isinstance(routes,dict) and set(routes)<=set(STAGES),'CONFIG_INVALID','模型路由阶段无效')
        for value in routes.values():
            require(isinstance(value,dict) and set(value)=={'model','rate'} and isinstance(value['model'],str) and 0<len(value['model'])<=100 and type(value['rate']) in (float,int) and 0<value['rate']<1,'CONFIG_INVALID','模型路由需明确 model 与每 Token 费用上限 rate')
    except (ValueError,TypeError):
        raise DomainError('CONFIG_INVALID','MODEL_ROUTES_JSON 格式无效') from None
    return Config(api_key=key,routes=routes)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise DomainError('PROVIDER_ERROR','模型接口发生重定向，已停止请求')


def decode_response(body):
    try:
        packet=json.loads(body)
        choice=packet['choices'][0]
        require(choice.get('finish_reason')=='stop','MODEL_OUTPUT_INVALID','模型输出不完整，未保存为稿件')
        value=json.loads(choice['message']['content'])
        require(isinstance(value,dict),'MODEL_OUTPUT_INVALID','模型未返回 JSON 对象')
        usage=packet.get('usage',{}); tokens=usage.get('total_tokens')
        require(type(tokens) is int and tokens>=0,'MODEL_OUTPUT_INVALID','模型未返回有效用量，保留预算预留')
        return value,tokens
    except DomainError: raise
    except (ValueError,KeyError,IndexError,TypeError):
        raise DomainError('MODEL_OUTPUT_INVALID','模型返回格式不正确，未自动重试') from None


class DeepSeek:
    THINKING_TYPE = 'disabled'
    MAX_OUTPUT_TOKENS = 3000
    def __init__(self, config): self.config=config

    def complete(self, messages):
        value,tokens,_ = self.complete_result(messages)
        return value,tokens

    def complete_result(self, messages):
        require(self.config.ready,'KEY_REQUIRED','请先填写 .env 的 DEEPSEEK_API_KEY 并重启服务')
        body=json.dumps({'model':self.config.model,'messages':messages,'stream':False,
                         'thinking':{'type':self.THINKING_TYPE},'max_tokens':self.MAX_OUTPUT_TOKENS,
                         'response_format':{'type':'json_object'}},ensure_ascii=False).encode()
        request=Request('https://api.deepseek.com/chat/completions',body,
                        {'Content-Type':'application/json','Authorization':'Bearer '+self.config.api_key})
        try:
            with build_opener(NoRedirect()).open(request,timeout=90) as response:
                raw=response.read(1_000_001)
                require(len(raw)<=1_000_000,'MODEL_OUTPUT_INVALID','模型响应过大')
            value,tokens=decode_response(raw)
            packet=json.loads(raw);usage=packet.get('usage',{})
            metadata={'request_id':packet.get('id')}
            for key,remote in (('input_tokens','prompt_tokens'),('output_tokens','completion_tokens')):
                n=usage.get(remote)
                metadata[key]=n if type(n) is int and n>=0 else None
            return value,tokens,metadata
        except HTTPError as e:
            message={401:'API Key 无效，请检查 .env',402:'DeepSeek 余额不足',429:'DeepSeek 请求受限，请稍后新建任务'}.get(e.code,'DeepSeek 暂时无法完成请求')
            raise DomainError('PROVIDER_ERROR',message+'；未自动重试') from None
        except (URLError,TimeoutError,OSError):
            raise DomainError('PROVIDER_ERROR','连接 DeepSeek 失败或超时；用量可能已产生，未自动重试') from None


def _provider_error(status, packet, secrets=()):
    """Keep vendor HTTP/code/message evidence, removing credentials and URLs."""
    import re
    descriptions={400:'请求参数或协议不受支持，请核对模型 ID 与接口协议',
        401:'API Key 鉴权失败',402:'账户余额或额度不足',403:'账号、模型或地区权限不足',
        404:'接口地址或模型不存在',408:'供应商处理超时',409:'供应商请求冲突',
        429:'请求受限或额度不足'}
    detail=packet.get('error',packet) if isinstance(packet,dict) else {}
    if isinstance(detail,str):detail={'message':detail}
    if not isinstance(detail,dict):detail={}
    code=detail.get('code') or detail.get('type')
    code=str(code) if isinstance(code,(str,int)) and not isinstance(code,bool) else ''
    message=detail.get('message') or detail.get('msg')
    message=message if isinstance(message,str) else ''
    text=' '.join(filter(None,[code,message]))
    for secret in secrets:
        if isinstance(secret,str) and secret:text=text.replace(secret,'[密钥已隐藏]')
    text=re.sub(r'(?i)\b(?:sk|sess|key)-[A-Za-z0-9_.*-]+','[密钥已隐藏]',text)
    text=re.sub(r'(?i)(?:bearer\s+)[^\s,;]+','Bearer [已隐藏]',text)
    text=re.sub(r'https?://[^\s<>]+','[供应商链接已隐藏]',text)
    text=' '.join(text.split())[:400]
    summary=descriptions.get(status,'供应商暂时不可用' if status>=500 else '供应商返回错误')
    return DomainError('PROVIDER_ERROR',f'HTTP {status} · {summary}'+(f'；供应商：{text}' if text else '')+'；未自动重试')


def connected_request(url,headers,payload):
    """Pin validated public DNS results to the socket; TLS retains original SNI.

    No environment proxy, redirect or transparent request retries are used.
    """
    import http.client
    import ipaddress
    import socket
    from urllib.parse import urlsplit
    parsed=urlsplit(url)
    secrets=[v.removeprefix('Bearer ') for k,v in headers.items() if k.lower() in ('authorization','x-api-key')]
    try:
        addresses=socket.getaddrinfo(parsed.hostname,443,type=socket.SOCK_STREAM)
        require(addresses and all(ipaddress.ip_address(a[4][0]).is_global for a in addresses),'PROVIDER_ERROR','模型地址解析到非公网网络，已停止')
        conn=http.client.HTTPSConnection(parsed.hostname,443,timeout=90)
        pinned=addresses[0][4][0]
        conn._create_connection=lambda address,timeout,source_address=None:socket.create_connection((pinned,443),timeout,source_address)
        try:
            conn.request('POST',parsed.path or '/',json.dumps(payload,ensure_ascii=False).encode(),headers)
            response=conn.getresponse()
            if response.status!=200:
                try:packet=json.loads(response.read(16385))
                except (ValueError,UnicodeError):packet={}
                raise _provider_error(response.status,packet,secrets)
            raw=response.read(1_000_001)
            require(len(raw)<=1_000_000,'MODEL_OUTPUT_INVALID','模型响应过大')
            packet=json.loads(raw)
            require(isinstance(packet,dict),'MODEL_OUTPUT_INVALID','模型服务返回的不是 JSON 响应对象')
            if packet.get('error'):raise _provider_error(200,packet,secrets)
            return packet
        finally:conn.close()
    except DomainError:raise
    except (OSError,TimeoutError,ValueError,http.client.HTTPException):
        raise DomainError('PROVIDER_ERROR','模型连接失败、超时或返回无效数据；用量可能已产生，未自动重试') from None


def _json_result(text):
    """Accept an exact JSON object or one enclosing code fence, never scrape prose."""
    import re
    require(isinstance(text,str),'MODEL_OUTPUT_INVALID','模型未返回文字内容')
    text=text.strip().lstrip('\ufeff')
    fence=re.fullmatch(r'```(?:json)?\s*\n?(.*?)\n?```',text,flags=re.I|re.S)
    if fence:text=fence[1].strip()
    try:value=json.loads(text)
    except ValueError:raise DomainError('MODEL_OUTPUT_INVALID','模型已响应，但输出不是完整 JSON 对象；请使用能遵循结构化指令的文本模型，或在高级设置启用其支持的 JSON 模式') from None
    require(isinstance(value,dict),'MODEL_OUTPUT_INVALID','模型必须返回 JSON 对象')
    return value


def _chat_text(content):
    if isinstance(content,str):return content
    require(isinstance(content,list),'MODEL_OUTPUT_INVALID','模型未返回文字内容')
    require(all(isinstance(part,dict) and part.get('type') in ('text','output_text') and isinstance(part.get('text'),str) for part in content),
            'MODEL_OUTPUT_INVALID','模型返回了不支持的内容类型')
    return ''.join(part['text'] for part in content)


def _openai_usage(usage,input_key,output_key):
    require(isinstance(usage,dict),'MODEL_OUTPUT_INVALID','模型未返回有效用量，保留预算预留')
    inp,out=usage.get(input_key),usage.get(output_key)
    for value in (inp,out):
        require(value is None or (type(value) is int and value>=0),'MODEL_OUTPUT_INVALID','模型用量报告无效')
    total=usage.get('total_tokens')
    if total is None and inp is not None and out is not None:total=inp+out
    require(type(total) is int and total>=0,'MODEL_OUTPUT_INVALID','模型未返回有效用量，保留预算预留')
    require(inp is None or out is None or total==inp+out,'MODEL_OUTPUT_INVALID','模型总用量与分项不一致')
    return total,inp,out


class ConnectedModel:
    """Three explicit text protocols with minimal, model-compatible payloads."""
    def __init__(self,connection,key):
        self.connection,self._key=connection,key

    def complete_result(self,messages,max_tokens=3000):
        import re
        from backend.model_connections import PROVIDERS,PROTOCOLS,base_url
        item=self.connection;provider=item['provider']
        protocol=item.get('protocol') or PROVIDERS[provider]['protocol']
        require(protocol in PROTOCOLS,'CONFIG_INVALID','模型接口协议无效')
        url=base_url(item['base_url'],protocol)
        headers={'Content-Type':'application/json'}
        if protocol=='responses':
            headers['Authorization']='Bearer '+self._key
            payload={'model':item['model'],'input':messages,'stream':False,'store':False,'max_output_tokens':max_tokens}
            if item.get('json_mode'):payload['text']={'format':{'type':'json_object'}}
            packet=connected_request(url+'/responses',headers,payload)
            try:
                require(packet.get('status')=='completed','MODEL_OUTPUT_INVALID','模型输出未完成，未自动重试')
                parts=[part for entry in packet['output'] if entry.get('type')=='message' for part in entry.get('content',[])]
                require(not any(part.get('type')=='refusal' for part in parts),'MODEL_OUTPUT_INVALID','模型拒绝了本次生成，未自动重试')
                value=_json_result(''.join(part['text'] for part in parts if part.get('type')=='output_text'))
                tokens,inp,out=_openai_usage(packet.get('usage'),'input_tokens','output_tokens')
                meta={'request_id':packet.get('id'),'input_tokens':inp,'output_tokens':out}
            except DomainError:raise
            except (ValueError,KeyError,TypeError,AttributeError):raise DomainError('MODEL_OUTPUT_INVALID','Responses 返回格式或用量无效，未自动重试') from None
        elif protocol=='anthropic':
            headers.update({'x-api-key':self._key,'anthropic-version':'2023-06-01'})
            payload={'model':item['model'],'max_tokens':max_tokens,'stream':False,
                     'system':'\n'.join(m['content'] for m in messages if m['role']=='system'),
                     'messages':[m for m in messages if m['role']!='system']}
            packet=connected_request(url+'/messages',headers,payload)
            try:
                require(packet.get('stop_reason') in ('end_turn','stop_sequence'),'MODEL_OUTPUT_INVALID','模型输出不完整')
                text=''.join(x['text'] for x in packet['content'] if x.get('type')=='text')
                value=_json_result(text);usage=packet['usage']
                usage_parts=[usage['input_tokens'],usage['output_tokens'],usage.get('cache_creation_input_tokens',0),usage.get('cache_read_input_tokens',0)]
                require(all(type(n) is int and n>=0 for n in usage_parts),'MODEL_OUTPUT_INVALID','模型用量报告无效')
                tokens=sum(usage_parts)
                meta={'request_id':packet.get('id'),'input_tokens':sum(usage_parts)-usage['output_tokens'],'output_tokens':usage['output_tokens']}
            except DomainError:raise
            except (ValueError,KeyError,TypeError,AttributeError):raise DomainError('MODEL_OUTPUT_INVALID','模型返回格式或用量无效，未自动重试') from None
        else:
            headers['Authorization']='Bearer '+self._key
            payload={'model':item['model'],'messages':messages,'stream':False}
            if item.get('json_mode'):payload['response_format']={'type':'json_object'}
            modern=provider=='openai' or bool(re.match(r'^(?:gpt-[5-9](?:[.-]|$)|o[134](?:-|$))',item['model'].split('/')[-1],re.I))
            payload['max_completion_tokens' if modern else 'max_tokens']=max_tokens
            # DashScope's original Qwen3 hybrid models require non-thinking mode
            # for synchronous calls. Never send this vendor flag to a gateway.
            from urllib.parse import urlsplit
            official_qwen=urlsplit(url).hostname in ('dashscope.aliyuncs.com','dashscope-intl.aliyuncs.com','dashscope-us.aliyuncs.com')
            hybrid_qwen=bool(re.match(r'^qwen3-\d+b(?:-|$)',item['model'],re.I)) and not re.search(r'(?:thinking|instruct)',item['model'],re.I)
            if official_qwen and hybrid_qwen:payload['enable_thinking']=False
            packet=connected_request(url+'/chat/completions',headers,payload)
            try:
                choice=packet['choices'][0];message=choice['message']
                require(choice.get('finish_reason')=='stop','MODEL_OUTPUT_INVALID','模型输出不完整，未保存为稿件')
                require(not message.get('refusal'),'MODEL_OUTPUT_INVALID','模型拒绝了本次生成，未自动重试')
                text=_chat_text(message.get('content'))
                if provider=='minimax':text=re.sub(r'^\s*<think>.*?</think>\s*','',text,count=1,flags=re.S)
                value=_json_result(text)
                tokens,inp,out=_openai_usage(packet.get('usage'),'prompt_tokens','completion_tokens')
                meta={'request_id':packet.get('id'),'input_tokens':inp,'output_tokens':out}
            except DomainError:raise
            except (ValueError,KeyError,IndexError,TypeError,AttributeError):raise DomainError('MODEL_OUTPUT_INVALID','Chat Completions 返回格式或用量无效，未自动重试') from None
        return value,tokens,meta
