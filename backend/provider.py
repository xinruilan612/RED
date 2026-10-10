"""DeepSeek text adapter. Secrets never enter Run, HTTP responses or error strings."""
import json
import math
import os
import re
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
    run_budget_usd: float = 0.20
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
    explicit_path = path is not None
    environment = os.environ if environ is None else environ
    path=Path(path) if explicit_path else ROOT/'.env'
    if (explicit_path or environment.get('YOUJI_IGNORE_PROJECT_ENV') != '1') and path.exists():
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


class ProviderOutputError(DomainError):
    """Safe parse failure carrying observed usage, never raw model output or secrets."""
    def __init__(self, message, *, tokens=None, metadata=None, diagnostic='content_invalid'):
        super().__init__('MODEL_OUTPUT_INVALID', message)
        self.tokens = tokens
        self.metadata = dict(metadata or {})
        self.diagnostic = diagnostic


def _strict_json(text):
    def object_pairs(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('duplicate key')
            value[key] = item
        return value

    def reject_constant(value):
        raise ValueError('non-finite number')

    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError('non-finite number')
        return number

    return json.loads(text, object_pairs_hook=object_pairs, parse_constant=reject_constant,
                      parse_float=finite_float)


def _decode_result(body):
    try:
        packet = _strict_json(body)
        if not isinstance(packet, dict):
            raise ValueError('envelope must be object')
    except (ValueError, TypeError, RecursionError):
        raise ProviderOutputError('模型响应无法读取，已保留任务；未自动重试',
                                  diagnostic='envelope_invalid') from None

    usage = packet.get('usage')
    usage = usage if isinstance(usage, dict) else {}
    tokens = usage.get('total_tokens')
    tokens = tokens if type(tokens) is int and tokens >= 0 else None
    request_id = packet.get('id')
    metadata = {'request_id': request_id if isinstance(request_id, str) and
                re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', request_id) else None}
    for key, remote in (('input_tokens', 'prompt_tokens'), ('output_tokens', 'completion_tokens')):
        n = usage.get(remote)
        metadata[key] = n if type(n) is int and n >= 0 else None

    def fail(message, diagnostic):
        raise ProviderOutputError(message, tokens=tokens, metadata=metadata, diagnostic=diagnostic)

    choices = packet.get('choices')
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        fail('模型响应缺少生成结果，已保留任务；未自动重试', 'envelope_invalid')
    choice = choices[0]
    if choice.get('finish_reason') != 'stop':
        fail('模型输出未完成，已保留任务；未自动重试',
             'output_truncated' if choice.get('finish_reason') == 'length' else 'output_incomplete')
    message = choice.get('message')
    content = message.get('content') if isinstance(message, dict) else None
    if not isinstance(content, str):
        fail('模型返回内容无法读取，已保留任务；未自动重试', 'content_invalid')
    content = content.strip()
    if not content:
        fail('模型返回了空内容，已保留任务；未自动重试', 'content_empty')
    # Remove only a complete outer code fence; never recover a guessed JSON fragment.
    fenced = re.fullmatch(r'```(?:json)?[ \t]*\r?\n(.*?)\r?\n```', content, re.DOTALL | re.IGNORECASE)
    if fenced:
        content = fenced.group(1).strip()
    try:
        value = _strict_json(content)
        if not isinstance(value, dict):
            raise ValueError('model output must be object')
    except (ValueError, TypeError, RecursionError):
        fail('模型返回格式暂时无法读取，已保留任务；未自动重试', 'content_invalid')
    if tokens is None:
        fail('模型未返回有效用量，保留预算预留；未自动重试', 'usage_missing')
    return value, tokens, metadata


def decode_response(body):
    value, tokens, _ = _decode_result(body)
    return value, tokens


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
                if len(raw) > 1_000_000:
                    raise ProviderOutputError('模型响应过大，已保留任务；未自动重试',
                                              diagnostic='response_too_large')
            return _decode_result(raw)
        except HTTPError as e:
            message={401:'API Key 无效，请检查 .env',402:'DeepSeek 余额不足',429:'DeepSeek 请求受限，请稍后新建任务'}.get(e.code,'DeepSeek 暂时无法完成请求')
            raise DomainError('PROVIDER_ERROR',message+'；未自动重试') from None
        except (URLError,TimeoutError,OSError):
            raise DomainError('PROVIDER_ERROR','连接 DeepSeek 失败或超时；用量可能已产生，未自动重试') from None
