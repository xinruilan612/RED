"""User-authorized, bounded public research; never infer platform heat from search."""
from datetime import datetime, timezone
from hashlib import sha256
from backend import sources
from backend.contracts import DomainError, require
from backend.knowledge import tokens


def selection(value, mode):
    if value is None: return {'enabled':False}
    require(isinstance(value,dict) and set(value)=={'enabled','queries'} and type(value['enabled']) is bool,
            'INVALID_INPUT','联网调查设置无效')
    queries=value['queries']
    require(isinstance(queries,list) and len(queries)<=2 and all(isinstance(q,str) and 2<=len(q.strip())<=120 for q in queries),
            'INVALID_INPUT','联网调查最多填写两个搜索词，每个 2–120 字')
    require(not value['enabled'] or (mode=='live' and queries),'INVALID_INPUT','请先选择真实 AI 并填写搜索词；模拟模式不联网')
    return {'enabled':value['enabled'],'queries':list(dict.fromkeys(q.strip() for q in queries)),'status':'pending'}


def collect(queries, before_request=lambda:None):
    report={'status':'insufficient','queries':queries,'searches':[],'reads':[],'sources':[],
            'searched_at':datetime.now(timezone.utc).isoformat(),'model_calls':0,
            'limits':{'searches':2,'reads':3,'excerpt_chars':400},
            'limitation':'公开搜索线索，不是平台热榜、评论全量数据或真实受众统计；读取正文不等于独立核实。'}
    candidates=[];seen=set()
    for query in queries[:2]:
        before_request()
        try:
            result=sources.search_web(query)
            rows=result['results'][:4]
            report['searches'].append({'query':query,'provider':result['provider'],'results':rows,'error':None})
            for row in rows:
                if row['url'] not in seen:
                    seen.add(row['url']);candidates.append(row)
        except DomainError as error:
            report['searches'].append({'query':query,'results':[],'error':str(error)})
    wanted=set(tokens(' '.join(queries)))
    for candidate in candidates[:3]:
        before_request()
        try:
            article=sources.read_article(candidate['url'])
            body=article['text'];matched=wanted & set(tokens(body))
            require(matched and not any(p in body[:600] for p in ('请完成安全验证','访问过于频繁','请输入验证码')),
                    'SOURCE_UNAVAILABLE','正文不相关或被验证页拦截，未作为证据')
            first=min(body.lower().find(t) for t in matched)
            offset=max(0,first-80);excerpt=body[offset:offset+400]
            report['sources'].append({'source_id':'web:'+sha256((article['url']+body).encode()).hexdigest()[:24],
                'title':article['title'],'url':article['url'],'text':excerpt,'offset':offset,'body_hash':sha256(body.encode()).hexdigest(),
                'source_type':'web','verification':article['verification'],'fetched_at':article['fetched_at'],
                'published_at':article.get('published_at'),'heat':None})
            report['reads'].append({'url':candidate['url'],'status':'read','error':None})
        except DomainError as error:
            report['reads'].append({'url':candidate['url'],'status':'failed','error':str(error)})
    if report['sources']: report['status']='complete'
    return report


def model_summary(report):
    """Do not send un-read snippets or full search responses to a model."""
    return {k:report[k] for k in ('status','queries','searched_at','limitation') if k in report}
