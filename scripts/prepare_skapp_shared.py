"""Encode a declared public training corpus using the website's actual encoder.

No scraping, invented labels or implicit private-account exports. Relative image
paths must stay inside the supplied dataset directory. License is a declaration,
not an independent legal verification.
"""
import argparse
import base64
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.topic_encoder import MODEL_NAME,encode
from scripts.skapp_personal import stamp


def prepare(data, root, encoder=encode):
    if not isinstance(data,dict) or data.get('data_scope')!='licensed_public' or not str(data.get('dataset_license','')).strip():
        raise ValueError('A public dataset and its license/permission declaration are required')
    if data.get('platform') not in ('xiaohongshu','douyin') or data.get('target_metric') not in ('views','likes','saves','comments') or data.get('window_hours') not in (24,72):
        raise ValueError('Specify platform, metric and 24/72-hour observation window')
    rows=data.get('records',[])
    if not isinstance(rows,list) or not 1<=len(rows)<=10000:
        raise ValueError('Supply 1..10000 actual records')
    root=Path(root).resolve(); pending=[]; ids=set()
    for row in rows:
        if not isinstance(row,dict) or not isinstance(row.get('id'),str) or not row['id'] or row['id'] in ids:
            raise ValueError('Each record needs a unique ID')
        ids.add(row['id'])
        for field in ('text','profile','author_id','profile_observed_at','published_at','observed_at','source_url','image_path'):
            if not isinstance(row.get(field),str) or not row[field].strip():
                raise ValueError('Missing required field: '+field)
        if len(row['text'])>10000 or len(row['profile'])>10000:raise ValueError('Text/profile exceeds encoder limit')
        if stamp(row['profile_observed_at'])>stamp(row['published_at']):raise ValueError('Profile must be known before publication')
        value=row.get('value')
        import math
        if type(value) not in (int,float) or not math.isfinite(value) or value<0:raise ValueError('Missing observed label; no zero filling')
        elapsed=(stamp(row['observed_at'])-stamp(row['published_at']))/3600
        if abs(elapsed-data['window_hours'])>data['window_hours']*.05:raise ValueError('Observation window mismatch')
        if not row['source_url'].startswith(('http://','https://')):raise ValueError('Source URL required')
        image=(root/row['image_path']).resolve()
        if not image.is_relative_to(root) or not image.is_file() or image.stat().st_size>3*1024*1024:raise ValueError('Image must be inside dataset directory and <=3 MB')
        mime={'.jpg':'image/jpeg','.jpeg':'image/jpeg','.png':'image/png','.webp':'image/webp'}.get(image.suffix.lower())
        if not mime:raise ValueError('Use JPG/PNG/WebP images')
        pending.append((row,image,mime))
    output=[]
    for start in range(0,len(pending),4):
        batch=pending[start:start+4]
        texts=[r[field] for r,_,_ in batch for field in ('text','profile')]
        images=['data:'+mime+';base64,'+base64.b64encode(path.read_bytes()).decode() for _,path,mime in batch]
        encoded=encoder(texts,images)
        if encoded['model']!=MODEL_NAME or len(encoded['text_vectors'])!=len(texts) or len(encoded['image_vectors'])!=len(images):raise ValueError('Encoder mismatch')
        for i,(row,_,_) in enumerate(batch):
            output.append({**{k:row[k] for k in ('id','author_id','profile_observed_at','published_at','observed_at','source_url','value')},'visual':encoded['image_vectors'][i],'textual':encoded['text_vectors'][2*i],'profile_vector':encoded['text_vectors'][2*i+1]})
    return dict(synthetic=data.get('synthetic') is True,schema_version=1,model_scope='shared',data_scope='licensed_public',encoder_id=MODEL_NAME,platform=data['platform'],target_metric=data['target_metric'],window_hours=data['window_hours'],dataset_license=data['dataset_license'],records=output)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--input',required=True);parser.add_argument('--output',required=True);args=parser.parse_args()
    source=Path(args.input);target=Path(args.output)
    if target.exists():parser.error('Output already exists')
    data=prepare(json.loads(source.read_text()),source.parent)
    target.parent.mkdir(parents=True,exist_ok=True)
    with target.open('x') as handle:json.dump(data,handle,ensure_ascii=False,allow_nan=False)
    print('Encoded records:',len(data['records']))


if __name__=='__main__':main()
