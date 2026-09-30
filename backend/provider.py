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
    def __init__(self, config): self.config=config

    def complete(self, messages):
        value,tokens,_ = self.complete_result(messages)
        return value,tokens

    def complete_result(self, messages):
        require(self.config.ready,'KEY_REQUIRED','请先填写 .env 的 DEEPSEEK_API_KEY 并重启服务')
        body=json.dumps({'model':self.config.model,'messages':messages,'stream':False,
                         'thinking':{'type':'disabled'},'max_tokens':3000,
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
