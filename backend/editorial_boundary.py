"""Keep creator-facing process notes out of reader-facing copy.

This is a narrow diagnostic for explicit process leakage, not a truth checker.
It never deletes text, manufactures evidence, approves a draft or calls a model.
"""
import copy
import hashlib
import re

_PATTERNS = (
    r'(?:网页|页面)(?:的)?发布时间(?:为|是)?空',
    r'已读(?:取)?(?:公开)?网页(?:正文)?',
    r'(?:素材|材料|资料)(?:里|中)(?:没有|未提供|未给出)[^。！？\n]{0,45}(?:依据|来源|顺序|片段)',
    r'后续找到(?:可标注)?来源[^。！？\n]{0,30}(?:补|拆解)',
)


def findings(content):
    result=[]
    for location in ('selected_title','body','cta','tags'):
        value=content.get(location,'')
        if isinstance(value,list):value=' '.join(value)
        if not isinstance(value,str):continue
        for sentence in re.findall(r'[^。！？\n]+[。！？]?',value):
            if any(re.search(pattern,sentence) for pattern in _PATTERNS):
                result.append({'location':location,'excerpt':sentence.strip()})
    return result


def annotate_review(report, content):
    """Preserve the response separately; downgrade only explicit copy leakage."""
    matches=findings(content)
    if not matches:return report
    result=copy.deepcopy(report)
    for match in matches:
        identity='copy-boundary-'+hashlib.sha256((match['location']+match['excerpt']).encode()).hexdigest()[:16]
        issue={**match,'issue_id':identity,'severity':'major','state':'open',
               'reason':'检测到给创作者的资料或处理说明混入读者正文，需要检查表达对象。',
               'suggestion':'将资料缺口留在工作台说明中；正文只写面向读者且有依据的内容。不得仅删除提示语后保留无依据的结论，也不要代博主承诺后续更新。'}
        result['issues']=[i for i in result['issues'] if i.get('issue_id')!=identity]+[issue]
        for previous in result.get('previous_issue_results',[]):
            if previous.get('issue_id')==identity:previous['result']='unresolved'
    for check in result['checks']:
        if check.get('name')=='usefulness_and_readability':
            check.update(result='fail',basis='正文包含创作过程或资料缺口说明，尚未区分内部说明与读者文案。')
    # A human can still adopt this draft explicitly. This is not an approval gate.
    result['decision']='needs_human';result['next_action']='request_human'
    question='请核对正文里的资料说明：若关键结论缺少依据，请补充对应原文；若已有依据，请将内部说明与发布正文分开。'
    if question not in result['human_questions']:result['human_questions'].append(question)
    result['limitations'].append('本地表达对象检查检测到明确的创作过程用语；没有核实外部事实，也没有自动修改原稿。')
    return result
