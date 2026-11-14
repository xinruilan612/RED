"""User-authorized, bounded public research; never infer platform heat from search."""
from datetime import datetime, timezone
from hashlib import sha256
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit
from backend import sources
from backend.contracts import DomainError, require
from backend.knowledge import tokens


def reference_urls(material, maximum=3):
    """Only links in the user's task material, never links discovered in a page.

    This is extraction, not permission to read a URL. Each candidate still goes
    through the normal public URL, DNS, redirect and source-access checks.
    """
    import re
    found=[]
    for match in re.finditer(r'https?://[^\s<>"\u3000]+', str(material or '')[:8000]):
        url=match.group().rstrip('.,;:!?，。；：！？、”’》】')
        for closing,opening in ((')','('),('）','（'),(']','[')):
            while url.endswith(closing) and url.count(closing)>url.count(opening):
                url=url[:-1]
        if url and url not in found:
            found.append(url)
        if len(found)>=maximum:break
    return found


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


def _spec_label(line):
    """A field name, never a value: no digits, no sentence ending, very short.

    The previous rule merged every line of eight characters or fewer into the
    previous line. That also merged ``28 厘米`` into ``深度`` *and then* merged
    the next value into the already merged pair, so a spec table became one
    scrambled run. A value line is data and must never act as a label.
    """
    import re
    return (0 < len(line) <= 6 and not re.search(r'\d', line)
            and not re.search(r'[。！？；:：]$', line))


def _spec_value(line):
    """A short data line that can be appended to the label before it.

    An already merged ``label value`` line is data too, but appending it to the
    preceding label would merge a section heading with the first spec and make
    normalization non-idempotent. Detect that shape and leave it alone.
    """
    import re
    if (len(line) > 12 or not re.search(r'\d', line)
            or re.search(r'[。！？；:：]$', line)):
        return False
    head, separator, tail = line.partition(' ')
    return not (separator and _spec_label(head) and re.search(r'\d', tail))


def normalize_body(body, maximum=400000):
    """Collapse table debris into quotable lines before freezing the snapshot.

    Official product pages deliver specs as alternating field/value lines mixed
    with navigation. The model then reorders and concatenates those cells, and a
    verbatim citation check cannot match the result. Merging a field label with
    the value line that follows makes each spec one contiguous, quotable line.
    Only whitespace, ordering of adjacent lines and noise are touched; no
    number, unit or model name is ever rewritten, and text with nothing to merge
    is returned byte-for-byte unchanged.
    """
    text = str(body or '')[:maximum]
    text = text.replace('\r\n', '\n').replace('\r', '\n').replace('\u00a0', ' ')
    noise = ('购物袋', '加入购物袋', '扫码下载', '我的收藏', '登录宜家', '搜索', '全部图片',
             '如何提货', '选择地址', '优惠明细', '切换地区', '查询商场库存', '下载APP')
    merged = []
    changed = False
    for raw in text.split('\n'):
        line = raw.strip()
        if not line:
            changed = changed or bool(raw)
            continue
        if any(word in line for word in noise):
            changed = True
            continue
        if merged and _spec_label(merged[-1]) and _spec_value(line):
            merged[-1] = merged[-1] + ' ' + line
            changed = True
        else:
            merged.append(line)
            changed = changed or line != raw
    if not changed:
        return text
    result = '\n'.join(merged)
    # Preserve the page's trailing newline so a no-merge body stays identical
    # and a merged body keeps the same outer shape.
    if text.endswith('\n') and result:
        result += '\n' * (len(text) - len(text.rstrip('\n')))
    return result


def _excerpt(body, queries, maximum=4000):
    """Keep a full short page or one original contiguous, relevant passage."""
    import re
    if len(body)<=maximum:return body,0
    wanted=set(tokens(' '.join(queries)))
    starts={0}
    lower=body.lower()
    for term in wanted:
        for match in list(re.finditer(re.escape(term.lower()),lower))[:12]:
            starts.add(max(0,match.start()-400))
    def score(start):
        window=body[start:start+maximum]
        overlap=len(wanted & set(tokens(window)))
        models=sum(sources.topic_match(query,window) for query in queries if sources.model_terms(query))
        return (models,overlap,min(len(re.findall(r'\d+(?:\.\d+)?',window)),20),-start)
    start=max(starts,key=score)
    # Preserve the exact original bytes/characters; avoid cutting a preceding line.
    boundary=body.rfind('\n',max(0,start-200),start)
    if boundary>=0:start=boundary+1
    end=min(len(body),start+maximum)
    if end<len(body):
        boundary=body.rfind('\n',max(start,end-400),end)
        if boundary>start:end=boundary
    return body[start:end],start


def collect(queries, before_request=lambda:None, searcher=None, source_urls=None, references_only=False):
    report={'status':'insufficient','queries':queries,'searches':[],'reads':[],'sources':[],
            'related_sources':[],'identity_limits':[],
            'searched_at':datetime.now(timezone.utc).isoformat(),'model_calls':0,
            'limits':{'searches':2,'supplemental_searches':1,'search_requests':4,'reads':8,'sources':3,'reference_urls':3,'excerpt_chars':4000},
            'limitation':'仅根据实际读到的网页正文提供证据。未查到或读取失败不证明产品未发布、不存在或某功能不支持；相关型号不能当作同一型号。搜索摘要不是正文，网页声明仍需核实。'}
    candidates=[];seen=set();blocked_hosts=set()

    def read_candidate(candidate):
        host=(urlsplit(candidate['url']).hostname or '').lower()
        if host in blocked_hosts:
            report['reads'].append({'url':candidate['url'],'status':'skipped','body_read':False,
                'candidate_origin':candidate.get('candidate_origin','search_result'),
                'error':'同一站点本次已拒绝读取，跳过后续链接并保留名额查找其他来源'})
            return
        before_request()
        try:
            from backend.research_access import require_readable_source
            require_readable_source(candidate['url'])
            article=sources.read_article(candidate['url']);body=article['text']
            require(not any(p in body[:800] for p in ('请完成安全验证','访问过于频繁','请输入验证码')),
                    'SOURCE_UNAVAILABLE','正文被验证页拦截，未作为证据')
            topic_text=article['title']+' '+body
            exact=any(sources.topic_match(query,topic_text) for query in queries)
            related=any(sources.related_model_match(query,topic_text) for query in queries)
            official=sources.official_priority(article)>0
            require(exact or related,'SOURCE_UNAVAILABLE','正文的主题或型号不匹配，未作为证据')
            quotable=normalize_body(body)
            excerpt,offset=_excerpt(quotable,queries)
            record={'source_id':'web:'+sha256((article['url']+body).encode()).hexdigest()[:24],
                'title':article['title'],'url':article['url'],'text':excerpt,'offset':offset,'body_hash':sha256(body.encode()).hexdigest(),
                'source_type':'web','verification':article['verification'],'fetched_at':article['fetched_at'],
                'published_at':article.get('published_at'),'heat':None,'body_read':True,
                'body_chars':len(body),'excerpt_truncated':len(excerpt)<len(quotable),
                'authority_hint':'official_candidate' if official else 'unverified_publisher',
                'candidate_origin':candidate.get('candidate_origin','search_result'),
                'model_match':'exact' if exact else 'related_unconfirmed'}
            if not exact:
                observed=[model for model in sources.model_terms(topic_text) if any(sources.related_model_match(query,model) for query in queries)][:12]
                requested=list(dict.fromkeys(model for q in queries for model in sources.model_terms(q)))
                record['identity_limit']={'requested_models':requested,'observed_models':observed,
                    'message':'本页只证明所列相关型号的信息；尚未证明它与用户所写型号为同一产品，不得移植参数、价格或发布状态。'}
                report['identity_limits'].append({'url':article['url'],**record['identity_limit']})
                report['related_sources'].append(record)
            if exact or official:report['sources'].append(record)
            report['reads'].append({'url':candidate['url'],'resolved_url':article['url'],'status':'read',
                'candidate_origin':candidate.get('candidate_origin','search_result'),
                'body_read':True,'model_match':record['model_match'],'fetched_at':article['fetched_at'],
                'published_at':article.get('published_at'),'body_chars':len(body),'error':None})
        except DomainError as error:
            if error.code in ('SOURCE_HTTP_403','SOURCE_HTTP_429'):
                blocked_hosts.add(host)
            report['reads'].append({'url':candidate['url'],'status':'failed','body_read':False,
                'candidate_origin':candidate.get('candidate_origin','search_result'),
                'error_code':error.code,'error':str(error)})

    def read_count():
        return sum(row['status']!='skipped' for row in report['reads'])

    # Author-provided product pages must not be crowded out by a search engine's
    # eight candidates. Failed reference reads use the same bounded read budget.
    for url in list(dict.fromkeys(source_urls or []))[:3]:
        seen.add(url)
        read_candidate({'url':url,'candidate_origin':'user_reference'})
        if len(report['sources'])>=3:break
    if len(report['sources'])<3 and not references_only:
        for query in queries[:2]:
            before_request()
            try:
                result=(searcher or sources.search_web)(query)
                rows=result['results'][:8];related=result.get('related_results',[])[:4]
                report['searches'].append({'query':query,'provider':result['provider'],
                    'effective_query':result.get('effective_query',query),'results':rows,'related_results':related,
                    'status':result.get('search_status','complete'),'attempts':result.get('attempts',[]),'error':None})
                for row in rows+related:
                    if row['url'] not in seen:
                        seen.add(row['url']);candidates.append(row)
            except DomainError as error:
                report['searches'].append({'query':query,'results':[],'status':'failed','error':str(error)})
        candidates.sort(key=sources.official_priority,reverse=True)
        for candidate in candidates:
            if len(report['sources'])>=3 or read_count()>=8:break
            read_candidate(candidate)
    # Only the default free, whole-web provider may supplement automatically.
    # Do not repeat a paid/custom provider or widen a user-selected site scope.
    requests=sum(max(1,len(row.get('attempts',[]))) for row in report['searches'])
    if not references_only and searcher is None and blocked_hosts and len(report['sources'])<3 and read_count()<8 and requests<4:
        excluded=sorted(blocked_hosts)
        def alternative_fetch(url):
            nonlocal requests
            require(requests<4,'SOURCE_UNAVAILABLE','本次搜索请求已达上限')
            before_request();requests+=1
            parts=urlsplit(url);params=parse_qs(parts.query)
            params['q']=[params['q'][0]+' '+' '.join('-site:'+host for host in excluded)]
            return sources.fetch_search(urlunsplit((parts.scheme,parts.netloc,parts.path,urlencode(params,doseq=True),'')))
        query=queries[0]
        try:
            result=sources.search_web(query,fetch=alternative_fetch)
            rows=result['results'][:8]+result.get('related_results',[])[:4]
            report['searches'].append({'query':query,'provider':result['provider'],
                'effective_query':result.get('effective_query',query)+' '+' '.join('-site:'+h for h in excluded),
                'supplemental':True,'excluded_domains':excluded,'results':result['results'][:8],
                'status':result.get('search_status','complete'),'attempts':result.get('attempts',[]),'error':None})
            for row in sorted(rows,key=sources.official_priority,reverse=True):
                if len(report['sources'])>=3 or read_count()>=8:break
                if row['url'] in seen:continue
                seen.add(row['url']);read_candidate({**row,'candidate_origin':'supplemental_search'})
        except DomainError as error:
            report['searches'].append({'query':query,'results':[],'supplemental':True,
                'excluded_domains':excluded,'status':'failed','error':str(error)})
        # A cancellation from the request guard must not become a source error.
        before_request()
    report['read_requests']=read_count()
    report['references_only']=references_only
    report['search_status']='failed' if report['searches'] and all(s['status']=='failed' for s in report['searches']) else (
        'partial_failure' if any(s['status'] in ('failed','partial_failure') for s in report['searches']) else 'complete')
    if report['sources']:report['status']='complete'
    elif report['search_status']=='failed':report['failure_kind']='search_failed'
    elif report['reads'] and all(r['status'] in ('failed','skipped') for r in report['reads']):report['failure_kind']='body_unavailable'
    else:report['failure_kind']='no_matching_evidence'
    return report


def model_summary(report):
    """Do not send un-read snippets or full search responses to a model."""
    summary={k:report[k] for k in ('status','queries','searched_at','search_status','failure_kind','identity_limits','limitation') if k in report}
    summary['reads']=[{k:row[k] for k in ('url','resolved_url','status','body_read','fetched_at','published_at','model_match','error') if k in row} for row in report.get('reads',[])]
    summary['related_sources']=[{k:row[k] for k in ('title','url','model_match','identity_limit','body_read','fetched_at','published_at') if k in row} for row in report.get('related_sources',[])]
    return summary


def attach_facts(context, report):
    """Freeze authorized, actually read web bodies in the task's factual group.

    Search snippets never enter this path. Task/topic filtering is independent
    of publishing channel; paid nodes consume this one frozen selection.
    """
    if 'creation_classification' not in context:
        context['evidence']=context.get('evidence',[])+report['sources']
        return
    from backend.creation_taxonomy import infer_domains
    classification=context['creation_classification'];domains=set(classification['domains'])
    retrieval=context['creation_retrieval'];groups=retrieval['groups']
    # Web research has a bounded evidence budget of its own. Existing uploads or
    # reference examples cannot crowd out actually read public factual sources.
    remaining=8000;accepted=[]
    for source in report['sources']:
        body=source.get('text','');topic_text=source.get('title','')+' '+body
        related=source.get('model_match')=='related_unconfirmed' and source.get('identity_limit')
        if not body or not (sources.topic_match(context['topic'],topic_text) or related):continue
        if len(accepted)>=3 or remaining<=0:break
        excerpt,shift=_excerpt(normalize_body(body),[context['topic']],min(4000,remaining))
        tags=set(infer_domains(topic_text))
        if domains!={'general'} and tags and not domains.intersection(tags):continue
        record={**source,'text':excerpt,'offset':source.get('offset',0)+shift,
                'excerpt_truncated':source.get('excerpt_truncated',False) or len(excerpt)<len(body),
                'material_type':'fact','evidence_role':'source_material',
                'classification':{'domains':sorted(tags & domains) or sorted(domains),'channel':'any','format':'any','material_type':'fact','origin':'task_scoped_web_read'}}
        accepted.append(record);remaining-=len(excerpt)
    # Refreshing research replaces only the previous web group; local documents
    # remain distinguishable reference material in the frozen retrieval snapshot.
    groups['facts']=accepted+[s for s in groups['facts'] if s.get('source_type')!='web']
    retrieval['sources']=[s for group in groups.values() for s in group]
    retrieval['context_chars']=sum(len(s['text']) for s in retrieval['sources'])
    retrieval['web_fact_filter']={'topic':context['topic'],'domains':sorted(domains),'channel':None,
        'read_body_only':True,'accepted':len(accepted),'max_chars':8000,'used_chars':8000-remaining,
        'related_model_limitations':bool(any(s.get('identity_limit') for s in accepted))}
    context['evidence']=retrieval['sources']
    report['sources']=accepted
    if not accepted:report['status']='insufficient'
