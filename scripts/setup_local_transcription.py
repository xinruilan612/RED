"""Explicit one-time public model download; runtime inference stays offline."""
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.local_transcription import MODEL_ID, MODEL_PATH, REVISION


def main():
    from huggingface_hub import snapshot_download
    MODEL_PATH.mkdir(parents=True,exist_ok=True)
    snapshot_download(MODEL_ID,revision=REVISION,local_dir=str(MODEL_PATH),
        allow_patterns=['*.json','*.txt','model.safetensors','README.md','LICENSE*'],
        max_workers=2)
    files={str(p.relative_to(MODEL_PATH)):hashlib.sha256(p.read_bytes()).hexdigest()
           for p in MODEL_PATH.rglob('*') if p.is_file() and '.cache' not in p.parts
           and p.name!='youji-model-manifest.json'}
    manifest={'model_id':MODEL_ID,'revision':REVISION,'source':f'https://huggingface.co/{MODEL_ID}/tree/{REVISION}',
              'license':'apache-2.0 (Hugging Face model repository metadata)',
              'files_sha256':files,'inference':'local CPU only; no paid API'}
    (MODEL_PATH/'youji-model-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    print(json.dumps({'model_id':MODEL_ID,'revision':REVISION,'files':len(files),'path':str(MODEL_PATH)}))


if __name__=='__main__':main()
