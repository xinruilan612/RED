"""Exact, version-bound draft references for reviewer citation output."""
import copy
import hashlib
import json
import re

from backend.contracts import require


def passages(content):
    """Split without rewriting text; IDs cannot refer to a different draft."""
    version=hashlib.sha256(json.dumps(content,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()[:12]
    result=[]
    for field in ('selected_title','body','cta','tags'):
        texts=content[field] if field=='tags' else [content[field]]
        for value in texts:
            pieces=re.findall(r'[^。！？\n]+[。！？]?|\n',value) if field=='body' else [value]
            for piece in pieces:
                if piece.strip():
                    result.append({'id':f'dp-{version}-{len(result)+1}','location':field,'text':piece})
    return result


def bind(value,content):
    """An explicit ID selects text, never fuzzy-match a model paraphrase."""
    result=copy.deepcopy(value)
    lookup={p['id']:p for p in passages(content)}
    entries=result.get('claim_map')
    if not isinstance(entries,list):return result
    for item in entries:
        if not isinstance(item,dict) or 'draft_excerpt_id' not in item:continue
        key=item['draft_excerpt_id']
        require(isinstance(key,str) and key in lookup,'MODEL_OUTPUT_INVALID','审核稿件片段编号无效或属于旧版')
        item['excerpt']=lookup[key]['text']
    return result
