"""Narrow output normalization for unsolicited template disclosures.

Runs before draft creation and hashing, never on already accepted drafts or exports.
Raw model responses remain in the call ledger; node logs record removals.
"""
import copy
import re

_SOURCE = r'(?:本文|本篇|本内容|内容)?(?:据|根据|依据|基于|由)?[^，,。；;！？\n]{0,30}(?:官网|官方|公开资料|公开信息|公开素材)[^，,。；;！？\n]{0,12}(?:整理|汇总|编写|撰写)'
_NEGATIVE = r'(?:非亲测|未经亲测|非实测|非品牌合作|无品牌合作|非合作推广)'
_TEMPLATE = re.compile(rf'^(?:{_SOURCE}|{_NEGATIVE})(?:[，,、；;\s]+{_NEGATIVE})*[。.!！]?$')
_DISCLOSURE = re.compile(r'来源(?:标注|声明)?|资料来源|免责声明|非亲测|非品牌合作|合作披露')
_REQUEST = re.compile(r'(?:保留|注明|标注|写明|披露|加上|添加|写上|必须写|需要写).{0,35}(?:来源|免责声明|非亲测|非品牌合作|合作)|(?:来源|免责声明|非亲测|非品牌合作).{0,20}(?:保留|注明|标注|写明|披露)')
_NEGATION = re.compile(r'不要|不必|无需|不用|删除|去掉|取消|不加')


def explicitly_requested(context):
    # Only user-authored fields count. Source documents and model analysis cannot
    # opt out of the policy or turn a product brochure into a user disclosure.
    request = context.get('revision_request', {})
    values = [context.get('topic', ''), context.get('tone', ''),
              request.get('feedback', '') if isinstance(request, dict) else '']
    for value in values:
        if not isinstance(value, str):
            continue
        for sentence in re.split(r'[。！？\n]', value):
            if _DISCLOSURE.search(sentence) and _REQUEST.search(sentence) and not _NEGATION.search(sentence):
                return True
    return False


def clean(stage, value, context):
    if stage not in ('body', 'revise') or not isinstance(value, dict) or explicitly_requested(context):
        return value, []
    result = copy.deepcopy(value)
    removed = []
    # Complete standalone sentences only. Never strip substrings from a factual
    # statement, genuine sponsorship, conditions or explicit personal experience.
    for field in ('body', 'cta'):
        if not isinstance(result.get(field), str):
            continue
        def replace(match):
            sentence = match.group(0)
            if sentence.strip() and _TEMPLATE.fullmatch(sentence.strip()):
                removed.append({'field': field, 'text': sentence.strip(), 'rule': 'default_disclosure@1'})
                return ''
            return sentence
        cleaned = re.sub(r'[^。！？!\n]+[。！？!]?|\n', replace, result[field])
        if any(item['field'] == field for item in removed):
            result[field] = re.sub(r'\n{3,}', '\n\n', cleaned).strip()
    return result, removed
