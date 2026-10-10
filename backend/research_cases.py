"""Versioned, owner-scoped research cases stored atomically in Knowledge.

No network access. Public articles must already have been read by the source
service. User imports attest permission, not platform verification or legality.
"""
from datetime import datetime, timezone
from backend.contracts import require, DomainError
from backend.demo import validate_text
from backend.knowledge import Knowledge
from backend.sources import public_url

METRICS = ('views', 'likes', 'favorites', 'comments', 'shares')
ROLES = ('expression_reference', 'product_fact')


def timestamp(value, label, optional=False):
    if value is None and optional:
        return None
    require(isinstance(value,str) and len(value)<=50, 'INVALID_INPUT', label+'需为带时区的 ISO 时间')
    try:
        parsed = datetime.fromisoformat(value.replace('Z','+00:00'))
        require(parsed.tzinfo is not None, 'INVALID_INPUT', label+'缺少时区')
        return parsed.astimezone(timezone.utc).isoformat()
    except (ValueError, TypeError):
        raise DomainError('INVALID_INPUT',label+'格式无效') from None


def candidate_assessment(metrics, published_at, observed_at, policy=None):
    """Explicit absolute heuristic, never a platform-wide viral assertion."""
    policy = {'min_interactions':1000, 'max_age_days':30} if policy is None else policy
    require(isinstance(policy,dict) and set(policy)=={'min_interactions','max_age_days'} and
            type(policy['min_interactions']) is int and 1<=policy['min_interactions']<=10**9 and
            type(policy['max_age_days']) is int and 1<=policy['max_age_days']<=3650,
            'INVALID_INPUT','高互动候选规则无效')
    missing = [key for key in METRICS if metrics.get(key) is None]
    known = [metrics[key] for key in ('likes','favorites','comments','shares') if metrics.get(key) is not None]
    total = sum(known) if known else None
    age = None
    if published_at and observed_at:
        age = (datetime.fromisoformat(observed_at)-datetime.fromisoformat(published_at)).total_seconds()/86400
    eligible = age is not None and 0<=age<=policy['max_age_days']
    candidate = eligible and total is not None and total>=policy['min_interactions']
    complete_interactions = all(metrics.get(key) is not None for key in ('likes','favorites','comments','shares'))
    rate = total / metrics['views'] if complete_interactions and metrics.get('views') and total is not None else None
    return {'status':'high_interaction_candidate' if candidate else 'insufficient' if not eligible or total is None else 'below_threshold',
            'known_interactions':total, 'interaction_rate':rate, 'age_days':age, 'missing_metrics':missing,
            'policy':dict(policy), 'limitation':'绝对阈值筛选；指标未独立核验，不是同类对照、爆款结论或效果保证'}


class ResearchCases:
    def __init__(self, store):
        self.knowledge = Knowledge(store)

    def save(self, owner, data, *, source_method="manual_import", fetched_at=None, transaction_guard=None, transaction_saved=None):
        allowed = {'account_id','title','text','source_url','platform','author','published_at','observed_at',
                   'content_kind','evidence_role','metrics','permission_confirmed','policy','document_id','expected_version'}
        require(isinstance(data,dict) and set(data)<=allowed, 'INVALID_INPUT','案例字段无效')
        self.knowledge.account(owner,data.get('account_id'))
        require(data.get('permission_confirmed') is True, 'INVALID_INPUT','请确认你有权保存并使用这份资料')
        kind = data.get('content_kind','text')
        role = data.get('evidence_role','expression_reference')
        require(kind in ('text','transcript','lead') and role in ROLES, 'INVALID_INPUT','案例内容或证据类别无效')
        require(not (kind=='lead' and role=='product_fact'), 'INVALID_INPUT','未读线索不能作为商品事实')
        url = public_url(data['source_url']) if data.get('source_url') else ''
        metrics = data.get('metrics',{})
        require(isinstance(metrics,dict) and set(metrics)<=set(METRICS), 'INVALID_INPUT','案例指标字段无效')
        require(all(v is None or (type(v) is int and 0<=v<=10**12) for v in metrics.values()),
                'INVALID_INPUT','指标必须为非负整数或 null')
        metrics = {key:metrics.get(key) for key in METRICS}
        published = timestamp(data.get('published_at'),'发布时间',True)
        observed = timestamp(data.get('observed_at'),'指标观察时间',True)
        require(not any(v is not None for v in metrics.values()) or observed is not None,
                'INVALID_INPUT','填写指标时必须提供观察时间')
        now = datetime.now(timezone.utc).isoformat()
        for value in (published,observed):
            require(value is None or datetime.fromisoformat(value)<=datetime.now(timezone.utc),
                    'INVALID_INPUT','来源时间不能在未来')
        require(not (published and observed) or published<=observed,'INVALID_INPUT','指标观察时间不能早于发布')
        case = {'schema_version':1,'platform':validate_text(data.get('platform','other'),'平台',60),
                'author':validate_text(data.get('author',''),'作者',200,allow_empty=True),
                'published_at':published,'observed_at':observed,'collected_at':now,
                'content_kind':kind,'evidence_role':role,'metrics':metrics,
                'permission':'user_attested','source_method':source_method,'fetched_at':fetched_at,
                'assessment':candidate_assessment(metrics,published,observed,data.get('policy')),
                'verification':'用户提供，尚未独立核验'}
        packet = {key:data[key] for key in ('account_id','title','text','document_id','expected_version') if key in data}
        result = self.knowledge.save(owner,packet,source_type='research_case',source_url=url,
            metadata={'research_case':case,'evidence_role':role,'retrieval_eligible':kind!='lead'},
            transaction_guard=transaction_guard,transaction_saved=transaction_saved)
        return result

    def from_article(self, owner, account_id, article, *, evidence_role='expression_reference', permission_confirmed=False, transaction_guard=None, transaction_saved=None):
        """Only for already-read full article packets, not search-result snippets."""
        require(isinstance(article,dict) and all(k in article for k in ('url','text','title','fetched_at','verification')),
                'INVALID_INPUT','需要已读取正文及采集信息，不能用搜索摘要替代')
        timestamp(article['fetched_at'],'网页读取时间')
        # This layer intentionally cannot access authenticated platform interfaces.
        from backend.research_access import require_readable_source
        require_readable_source(article['url'])
        return self.save(owner,{'account_id':account_id,'title':article['title'],'text':article['text'],
            'source_url':article['url'],'platform':'public_web','content_kind':'text',
            'evidence_role':evidence_role,'permission_confirmed':permission_confirmed,
            'published_at':article.get('published_at'),'observed_at':article['fetched_at']},source_method='read_public_web',fetched_at=article['fetched_at'],transaction_guard=transaction_guard,transaction_saved=transaction_saved)

    def list(self, owner, account_id):
        return [doc for doc in self.knowledge.list(owner,account_id) if doc['source_type']=='research_case']

    def export(self, owner, account_id, document_ids=None, title='案例研究文档'):
        title = validate_text(title,'文档标题',200)
        docs = self.list(owner,account_id)
        if document_ids is not None:
            require(isinstance(document_ids,list) and len(document_ids)<=100 and all(isinstance(i,str) for i in document_ids),
                    'INVALID_INPUT','导出案例列表无效')
            chosen = set(document_ids)
            require(chosen<=set(doc['id'] for doc in docs),'RESOURCE_NOT_FOUND','案例不可访问或已失效')
            docs = [doc for doc in docs if doc['id'] in chosen]
        lines = ['# '+safe(title),'','导出范围：当前账号选定的有效案例，共 '+str(len(docs))+' 条；不是全平台完整集合。',
                 '指标未独立核验；未知保留为空。表达参考与商品事实分开，不移植他人体验或产品功效。','']
        for doc in docs:
            full = self.knowledge.get(owner,account_id,doc['id'])
            case = full['metadata']['research_case']
            lines += ['## '+safe(full['title']),'',f"资料 ID：{full['id']}；版本：{full['version']}",
                '类别：'+('商品事实（待核验）' if case['evidence_role']=='product_fact' else '表达参考'),
                '内容：'+case['content_kind']+'；来源：'+safe(full['source_url'] or '用户资料，无公开链接'),
                '作者：'+safe(case['author'] or '未知'),
                '发布时间：'+(case['published_at'] or '未知')+'；指标观察时间：'+(case['observed_at'] or '未知'),
                '采集时间：'+case['collected_at'], '', '| 指标 | 数值 |','| --- | --- |']
            lines += ['| '+key+' | '+('未知' if value is None else str(value))+' |' for key,value in case['metrics'].items()]
            assessment = case['assessment']
            lines += ['', '筛选：'+assessment['status']+'；规则：'+str(assessment['policy']['max_age_days'])+' 天内、已知互动至少 '+str(assessment['policy']['min_interactions'])+'。',
                      assessment['limitation'],'','### 原文 / 字幕 / 未读线索','']
            # Overlapping chunks are joined by source offsets, not duplicated.
            body = ''
            for chunk in full['chunks']:
                end = chunk['offset']+len(chunk['text'])
                if end>len(body): body += chunk['text'][max(0,len(body)-chunk['offset']):]
            lines += ['> '+safe(line) for line in body.splitlines()]
            lines += ['']
        return {'filename':'research-cases.md','content':'\n'.join(lines),'count':len(docs),'format':'markdown'}


def safe(value):
    """Keep imported text from creating active HTML, images, or links in exports."""
    return str(value).replace('&','&amp;').replace('<','&lt;').replace('>','&gt;').replace('\\','\\\\').replace('[','\\[').replace(']','\\]').replace('`','\\`').replace('\r','').replace('\n',' ')
