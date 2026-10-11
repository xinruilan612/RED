"""User-authorized, bounded public research; never infer platform heat from search."""
from datetime import datetime, timezone
from hashlib import sha256
from backend import sources
from backend.contracts import DomainError, require
from backend.knowledge import tokens


def selection(value, mode):
    if value is None: return {'enabled':False}
    require(isinstance(value,dict) and {'enabled','queries'}<=set(value)<={'enabled','queries','provider','targets'} and type(value['enabled']) is bool,
            'INVALID_INPUT','联网调查设置无效')
    queries=value['queries']
    require(isinstance(queries,list) and len(queries)<=2 and all(isinstance(q,str) and 2<=len(q.strip())<=120 for q in queries),
            'INVALID_INPUT','联网调查最多填写两个搜索词，每个 2–120 字')
    require(not value['enabled'] or (mode=='live' and queries),'INVALID_INPUT','请先选择真实 AI 并填写搜索词；模拟模式不联网')
    from backend.search_providers import target_domains
    provider=value.get('provider','bing');targets=value.get('targets',['web'])
    require(provider in ('bing','wikipedia','baidu'),'INVALID_INPUT','搜索服务无效')
    target_domains(targets)
    require(provider!='wikipedia' or targets==['web'],'INVALID_INPUT','百科搜索不支持平台范围')
    return {'enabled':value['enabled'],'queries':list(dict.fromkeys(q.strip() for q in queries)),
            'provider':provider,'targets':targets,'status':'pending'}


def collect(queries, before_request=lambda:None, searcher=None):
    report={'status':'insufficient','queries':queries,'searches':[],'reads':[],'sources':[],
            'searched_at':datetime.now(timezone.utc).isoformat(),'model_calls':0,
            'limits':{'searches':2,'reads':6,'excerpt_chars':400},
            'limitation':'公开搜索线索，不是平台热榜、评论全量数据或真实受众统计；读取正文不等于独立核实。'}
    candidates=[];seen=set()
    for query in queries[:2]:
        before_request()
        try:
            result=(searcher or sources.search_web)(query)
            rows=result['results'][:8]
            report['searches'].append({'query':query,'provider':result['provider'],'effective_query':result.get('effective_query',query),'results':rows,'error':None})
            for row in rows:
                if row['url'] not in seen:
                    seen.add(row['url']);candidates.append(row)
        except DomainError as error:
            report['searches'].append({'query':query,'results':[],'error':str(error)})
    wanted=set(tokens(' '.join(queries)))
    for candidate in candidates[:6]:
        if len(report['sources'])>=3: break
        before_request()
        try:
            from backend.research_access import require_readable_source
            require_readable_source(candidate['url'])
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


def attach_facts(context, report):
    """Freeze authorized, actually read web bodies in the task's factual group.

    Search snippets never enter this path. Task/topic filtering is independent
    of publishing channel; paid nodes consume this one frozen selection.
    """
    if 'creation_classification' not in context:
        context['evidence']=context.get('evidence',[])+report['sources']
        return
    import re
    from backend.creation_taxonomy import infer_domains, taxonomy
    classification=context['creation_classification'];domains=set(classification['domains'])
    retrieval=context['creation_retrieval'];groups=retrieval['groups'];limits=taxonomy()['retrieval']
    remaining=max(0,limits['total_chars']-sum(len(s['text']) for group in groups.values() for s in group))
    wanted=set(tokens(context['topic']))
    product_ids=set(re.findall(r'(?<![A-Za-z0-9_-])(?=[A-Za-z0-9_-]*\d)[A-Za-z][A-Za-z0-9_-]{1,}(?![A-Za-z0-9_-])',context['topic']))
    accepted=[]
    for source in report['sources']:
        body=source.get('text','');topic_text=source.get('title','')+' '+body
        tags=set(infer_domains(topic_text));matched=wanted & set(tokens(topic_text))
        if not body or not matched or (len(wanted)>3 and len(matched)<2):continue
        if domains!={'general'} and tags and not domains.intersection(tags):continue
        if product_ids and not all(re.search(r'(?<![A-Za-z0-9_-])'+re.escape(p)+r'(?![A-Za-z0-9_-])',topic_text,re.I) for p in product_ids):continue
        if len(groups['facts'])>=limits['limits']['facts'] or remaining<=0:break
        record={**source,'text':body[:min(remaining,limits['chunk_chars'])],
                'material_type':'fact','evidence_role':'source_material',
                'classification':{'domains':sorted(tags & domains) or sorted(domains),'channel':'any','format':'any','material_type':'fact','origin':'task_scoped_web_read'}}
        groups['facts'].append(record);accepted.append(record);remaining-=len(record['text'])
    retrieval['sources']=[s for group in groups.values() for s in group]
    retrieval['context_chars']=limits['total_chars']-remaining
    retrieval['web_fact_filter']={'topic':context['topic'],'domains':sorted(domains),'channel':None,'read_body_only':True,'accepted':len(accepted)}
    context['evidence']=retrieval['sources']
    report['sources']=accepted
    if not accepted:report['status']='insufficient'
