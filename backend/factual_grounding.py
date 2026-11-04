"""Narrow diagnostics for uncited specifications and invented search coverage.

This is not a fact checker: even a valid source quotation can be false, outdated,
or about another product. Never manufactures sources, rewrites copy or approves it.
"""
import copy
import hashlib
import re

_SPECS = re.compile(
    r'\d+(?:\.\d+)?\s*(?:K\s*\d+\s*fps|K\s*\d+\s*[pP]|fps|mAh|MP|GB|TB|Hz|英寸|万像素|元|美元)'
    r'|(?:一|两|三|四|五|六|七|八|九|十)英寸'
    r'|20\d{2}年\d{1,2}月(?:\d{1,2}日)?(?=.{0,8}(?:发布|上市|发售))', re.I)
_ABSENCE = re.compile(r'(?:尚未|从未|并未|没有|未)(?:正式)?(?:发布|上市|发售)|无(?:任何)?(?:发布信息|参数|官方依据)|不可购|(?:根本|压根)(?:没出|没有)|(?:并)?不存在|官网只有')
_SWEEP = re.compile(
    r'(?:官网|官方旗舰店|权威.{0,5}媒体|全球新闻稿).{0,100}(?:均无|都没有|全无|均未|任何发布信息)'
    r'|(?:查遍|搜遍|检索了所有|全网(?:搜索|检索|查证)).{0,60}')
_SEARCH = re.compile(r'(?:我(?:们)?|已|经过|经)(?:经|实际|经逐一)?(?:搜索|检索|查证|核查|核实|查阅|查询).{0,30}(?:官网|网站|媒体|旗舰店)')

# These are narrow, high-risk writing claims, not a semantic entailment model.
# A USB connector/dimensions cannot establish setup simplicity or comfort.
_PROPERTY_CLAIMS = [
    ('即插即用', re.compile(r'即插即用|插上就能用|插上(?:就|即可)(?:使用|开用)|无需(?:安装|下载)(?:任何)?驱动')),
    ('握持体验', re.compile(r'握感(?:舒适|舒服)|握持(?:舒适|舒服)')),
    ('握感适中', re.compile(r'握感适中')),
    ('久用疲劳', re.compile(r'(?:久用|用久|长时间使用)(?:也)?不累')),
    ('静音体验', re.compile(r'完全(?:静音|无声)|(?:点击|按键|使用)(?:时)?(?:没有|毫无)噪[音声]')),
    ('兼容范围', re.compile(r'(?:兼容|适用|支持)(?:所有|任何|一切)(?:电脑|设备|系统)|(?:所有|任何)系统(?:都)?(?:能用|可用|兼容)')),
    ('直接连接', re.compile(r'可直连|能够直连|能直接连接')),
    ('需求满足', re.compile(r'完全够用')),
    ('选购保证', re.compile(r'放心选')),
    ('不卡顿保证', re.compile(r'绝不卡顿|不会卡顿')),
    ('负载能力', re.compile(r'轻松带动')),
    ('视频功能限制', re.compile(r'不支持视频输出|不能输出视频')),
    ('充电功能限制', re.compile(r'不支持(?:视频输出或)?充电|不能充电')),
    ('公开范围', re.compile(r'(?:官方|关键参数).{0,8}未公开|(?:电池寿命|DPI|机身尺寸).{0,12}未公开')),
    ('多设备切换', re.compile(r'多设备切换|跨设备切换')),
    ('紧固范围', re.compile(r'拧紧所有螺丝|紧固所有螺丝')),
    ('亲历体验', re.compile(r'我(?:本人|自己)?(?:已经|连续|亲自)?(?:用了|使用了|实测|亲测|试用了|体验了)')),
]
_UNCERTAIN = re.compile(r'尚未|还未|未曾|未提供|未实测|未测试|未确认|未经|没有.{0,6}(?:依据|记录|实测)|未知|不确定|能否|是否|与否|不代表|不能(?:证明|保证)|无法(?:证明|保证)|待(?:确认|核对)|请.{0,6}(?:确认|核对)|建议.{0,6}(?:确认|核对)')


# Deliberately conservative lexical guards, not semantic entailment. Conditions
# are compared literally (apart from whitespace/case); paraphrases need a human.
_NEGATION = re.compile(r'(?:不是|并非|不具备|不支持|无法|不能|不可|不)(?:真正|完全)?$')
_CONDITION = re.compile(r'仅|只在|只有|如果|若|需要|需先|必须|安装后|连接后|前提|条件|时才|才能|在.{1,30}(?:下|上|时)')
_CLAUSES = re.compile(r'(?:(?!但是|不过|然而|但)[^，,；;。！？\n])+')


def _property_contexts(pattern, value):
    """Yield each positive occurrence and its local constraints and offsets."""
    preceding = []
    for part in _CLAUSES.finditer(value):
        clause = part.group().strip()
        for match in pattern.finditer(part.group()):
            prefix = part.group()[:match.start()].strip()
            if _UNCERTAIN.search(clause) or _NEGATION.search(prefix):
                continue
            # A condition in an earlier clause governs following assertions unless
            # an explicit sentence boundary intervenes. Do not silently discard it.
            constraints = list(preceding)
            remainder = part.group()[:match.start()] + part.group()[match.end():]
            if _CONDITION.search(remainder):
                constraints.append(remainder.strip())
            yield (part.start()+match.start(), part.start()+match.end(), constraints)
        if _CONDITION.search(clause):
            preceding.append(clause)
        following = value[part.end():part.end()+1]
        if following in '。！？\n':
            preceding = []


def _property_supported(pattern, sentence, occurrence, claim_map, lookup):
    start, end, constraints = occurrence
    fold = lambda text: re.sub(r'\s+', '', text).lower()
    for item in claim_map:
        excerpt, quote = item.get('excerpt', ''), item.get('quote', '')
        if not excerpt or item.get('source_id') not in lookup:
            continue
        if lookup[item['source_id']].get('content_kind') == 'lead':
            continue
        # The cited excerpt must actually cover this occurrence, not just another
        # assertion with the same property elsewhere in the sentence.
        positions = [m.start() for m in re.finditer(re.escape(excerpt), sentence)]
        if not any(p <= start and end <= p+len(excerpt) for p in positions):
            continue
        # Read context from the actual source, so quoting only 即插即用 cannot
        # remove a surrounding 不是 / 仅在Windows... restriction.
        source_text = lookup[item['source_id']].get('text', '')
        if not quote or not source_text:
            continue
        quote_positions = [m.start() for m in re.finditer(re.escape(quote), source_text)]
        for a, b, source_constraints in _property_contexts(pattern, source_text):
            if not any(p <= a and b <= p+len(quote) for p in quote_positions):
                continue
            if all(fold(c) in {fold(v) for v in constraints} for c in source_constraints):
                return True
    return False


def findings(content, claim_map, sources, web_report):
    """Quotes are already strictly validated by live.normalize before this call."""
    lookup={s['source_id']:s for s in sources}
    # A successful search alone does not prove that a claimed website was read.
    read_urls={r.get('url') for r in web_report.get('reads',[]) if r.get('status')=='read' and r.get('url')}
    result=[]
    for location in ('selected_title','body','cta','tags'):
        value=content.get(location,'')
        if isinstance(value,list):value='\n'.join(value)
        if not isinstance(value,str):continue
        for sentence in re.findall(r'[^。！？\n]+[。！？]?',value):
            sentence=sentence.strip()
            reason=None
            process_cited=any(item.get('excerpt','') in sentence
                              and lookup.get(item.get('source_id'),{}).get('url') in read_urls
                              for item in claim_map)
            if _SWEEP.search(sentence) or (_SEARCH.search(sentence) and not process_cited):
                reason='文案宣称全面查证或已读取网站，实际检索记录不足以支持此过程与覆盖范围。'
            for match in list(_SPECS.finditer(sentence))+list(_ABSENCE.finditer(sentence)):
                span=match.group()
                supported=any(
                    span in item.get('excerpt','') and span in item.get('quote','')
                    and item.get('excerpt','') in sentence
                    and item.get('source_id') in lookup
                    and lookup[item['source_id']].get('content_kind')!='lead'
                    for item in claim_map)
                if not supported:
                    reason=reason or '具体规格、价格、发布日期或未发布结论缺少对应原文引文；未取得证据不能推成产品不存在。'
            for label, pattern in _PROPERTY_CLAIMS:
                for occurrence in _property_contexts(pattern, sentence):
                    if not _property_supported(pattern, sentence, occurrence, claim_map, lookup):
                        reason=reason or label+'属于新增使用结论，现有引用没有对应的明确记录；接口、尺寸或品牌介绍不能替代该体验或适用性依据。'
            if reason:result.append({'location':location,'excerpt':sentence,'reason':reason})
    return result


def annotate_review(report, content, sources, web_report):
    matches=findings(content,report['claim_map'],sources,web_report)
    if not matches:return report
    result=copy.deepcopy(report)
    for match in matches:
        identity='fact-grounding-'+hashlib.sha256((match['location']+match['excerpt']).encode()).hexdigest()[:16]
        issue={**match,'issue_id':identity,'severity':'major','state':'open',
               'suggestion':'用本次实际取得且匹配对象、条件与时间的来源核对该句并补齐引用；无法支持时删除或缩小该主张，体验须有真实记录。'}
        result['issues']=[i for i in result['issues'] if i.get('issue_id')!=identity]+[issue]
        for previous in result.get('previous_issue_results',[]):
            if previous.get('issue_id')==identity:previous['result']='unresolved'
    for check in result['checks']:
        if check.get('name')=='evidence_integrity':
            check.update(result='fail',basis='检测到没有对应引文的具体外部事实或缺乏实际记录的检索覆盖断言。')
    result.update(decision='needs_human',next_action='request_human')
    question='请核对标记的事实与真实来源；该稿尚未通过事实审核，不能视为已核实结论。'
    if question not in result['human_questions']:result['human_questions'].append(question)
    result['limitations'].append('本地有限模式检查只覆盖部分规格、检索断言与使用体验表达；引文存在不代表事实正确，也不是全面事实核查。')
    return result
