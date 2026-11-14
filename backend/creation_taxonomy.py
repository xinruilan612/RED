"""Configurable creation classifications; inference is labelled, never evidence."""
import json
import re
from pathlib import Path
from backend.contracts import require


def taxonomy():
    return json.loads((Path(__file__).parent.parent/'config/creation_taxonomy.json').read_text(encoding='utf-8'))


def _validated(value, document=False):
    require(isinstance(value, dict), 'INVALID_INPUT', '分类信息格式不正确，请重新选择领域、渠道和内容形式后提交。')
    cfg = taxonomy()
    allowed = {'domains', 'channel', 'format', 'goal', 'word_count', 'origin', 'ambiguities', 'material_type'}
    require(set(value) <= allowed, 'INVALID_INPUT', '分类信息包含不支持的字段，请刷新页面后重新选择分类再提交。')
    result = dict(value)
    domains = value.get('domains', [])
    require(isinstance(domains, list), 'INVALID_INPUT', '领域格式不正确，请在领域选项中勾选，最多选择 8 项。')
    require(len(domains) <= 8, 'INVALID_INPUT', f'领域最多选择 8 项，当前提交了 {len(domains)} 项；请取消多余选项后重试。')
    require(all(isinstance(d, str) for d in domains), 'INVALID_INPUT', '领域中包含格式不正确的选项，请取消这些选项并从领域列表重新选择。')
    unknown = [d for d in domains if d not in cfg['domains']]
    if unknown:
        names = '、'.join('“' + d[:40] + ('…' if len(d) > 40 else '') + '”' for d in unknown)
        labels = '、'.join(item['label'] for item in cfg['domains'].values())
        require(False, 'INVALID_INPUT', f'领域 {names} 不在可选分类中。请从领域选项重新选择，最多 8 项；可选分类：{labels}。')
    result['domains'] = list(dict.fromkeys(domains))
    for field, key, label in (('channel', 'channels', '渠道'), ('format', 'formats', '内容形式')):
        if field in value and value[field] is not None and value[field] != '':
            selected = value[field]
            valid = isinstance(selected, str) and (selected in cfg[key] or (document and selected == 'any'))
            options = '、'.join(item['label'] for item in cfg[key].values()) + ('、不限' if document else '')
            require(valid, 'INVALID_INPUT', f'{label}选项无效，请重新选择：{options}。')
    if document:
        require(value.get('material_type') in ('method', 'example', 'fact'), 'INVALID_INPUT',
                '资料用途未选择或无效，请选择“通用创作方法”“领域参考样例”或“事实资料”后重试。')
    if 'word_count' in value:
        require(type(value['word_count']) is int, 'INVALID_INPUT', '目标字数格式不正确，请输入 20 至 10000 之间的整数，不要填写小数、单位或文字。')
        require(20 <= value['word_count'] <= 10000, 'INVALID_INPUT', f'目标字数需在 20 至 10000 之间，当前为 {value["word_count"]}；请修改后重试。')
    if 'goal' in value:
        require(isinstance(value['goal'], str), 'INVALID_INPUT', '创作目标格式不正确，请填写文字，最多 300 字。')
        require(len(value['goal']) <= 300, 'INVALID_INPUT', f'创作目标最多 300 字，当前为 {len(value["goal"])} 字；请删减后重试。')
    return result


def infer_domains(text):
    return [key for key,item in taxonomy()['domains'].items() if key!='general' and any(term.lower() in text.lower() for term in item['keywords'])]


def classify_task(creation=None,context=None):
    context=context or {}; supplied=_validated({} if creation is None else creation)
    text=' '.join(str(context.get(k,'')) for k in ('topic','material','audience'))
    domains=supplied.get('domains') or infer_domains(text)
    form=supplied.get('format') or ('video_script' if re.search('口播|视频脚本|短视频',text) else 'product_detail' if '商品详情' in text else 'note')
    ambiguities=[]
    if not domains and re.search('苹果',str(context.get('topic',''))):
        require(False,'CREATION_CLASSIFICATION_REQUIRED','当前主题领域不明确，请选择领域或补充产品类型')
    return {**supplied,'domains':domains or ['general'],'channel':supplied.get('channel') or 'xiaohongshu','format':form,
            'origin':'user' if supplied.get('domains') else 'inferred','ambiguities':ambiguities}


def classify_document(value, title, text, metadata=None):
    if value is not None:
        result=_validated(value,True)
        require(result['domains'] or result['material_type']=='method','INVALID_INPUT','领域参考样例和事实资料至少需要选择 1 个领域，请在领域选项中勾选后重试；通用创作方法可以不选。')
        return {**result,'channel':result.get('channel','any'),'format':result.get('format','any'),'origin':'user'}
    metadata=metadata or {};case=metadata.get('research_case',{})
    example=metadata.get('evidence_role') in ('expression_reference','reference_only') or case.get('evidence_role') in ('expression_reference','reference_only')
    kind='example' if example else 'fact'
    domains=infer_domains(title+' '+text)
    channel='xiaohongshu' if case.get('platform') in ('xiaohongshu','小红书') or 'xiaohongshu.com' in metadata.get('source_url','') else 'any'
    provenance=case.get('provenance',{})
    is_video=(case.get('content_kind') in ('video','transcript','video_description')
              or case.get('source_method') in ('local_browser_video_description','human_reviewed_transcript')
              or provenance.get('content_type')=='video' or provenance.get('body_kind')=='video_description')
    form='video_script' if is_video else 'note' if channel=='xiaohongshu' else 'any'
    return {'domains':domains,'channel':channel,'format':form,'material_type':kind,'origin':'inferred','ambiguities':[] if domains else ['domain_unknown']}
