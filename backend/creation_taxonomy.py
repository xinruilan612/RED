"""Configurable creation classifications; inference is labelled, never evidence."""
import json
import re
from pathlib import Path
from backend.contracts import require


def taxonomy():
    return json.loads((Path(__file__).parent.parent/'config/creation_taxonomy.json').read_text())


def _validated(value, document=False):
    require(isinstance(value,dict),'INVALID_INPUT','分类必须为对象')
    cfg=taxonomy()
    allowed={'domains','channel','format','goal','word_count','origin','ambiguities','material_type'}
    require(set(value)<=allowed,'INVALID_INPUT','分类字段无效')
    result=dict(value)
    domains=value.get('domains',[])
    require(isinstance(domains,list) and len(domains)<=8 and all(isinstance(d,str) and d in cfg['domains'] for d in domains),'INVALID_INPUT','领域必须使用已配置分类，可多选')
    result['domains']=list(dict.fromkeys(domains))
    for field,key in (('channel','channels'),('format','formats')):
        if value.get(field):require(value[field] in cfg[key] or (document and value[field]=='any'),'INVALID_INPUT','渠道或形式不在分类配置中')
    if document:require(value.get('material_type') in ('method','example','fact'),'INVALID_INPUT','材料类型必须为 method/example/fact')
    if 'word_count' in value:require(type(value['word_count']) is int and 20<=value['word_count']<=10000,'INVALID_INPUT','字数需为20至10000')
    if 'goal' in value:require(isinstance(value['goal'],str) and len(value['goal'])<=300,'INVALID_INPUT','目标过长')
    return result


def infer_domains(text):
    return [key for key,item in taxonomy()['domains'].items() if key!='general' and any(term.lower() in text.lower() for term in item['keywords'])]


def classify_task(creation=None,context=None):
    context=context or {}; supplied=_validated(creation or {})
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
        require(result['domains'] or result['material_type']=='method','INVALID_INPUT','样例和事实资料需指定领域')
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
