"""Explicit maintenance command: fetch pinned public model, never user content."""
from pathlib import Path
import hashlib
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
MODEL='OFA-Sys/chinese-clip-vit-base-patch16'
REVISION='36e679e65c2a2fead755ae21162091293ad37834'

def main():
    if Path(sys.prefix).resolve()==(ROOT/'runtime/venv').resolve():
        raise SystemExit('Use runtime/skapp/venv, not the website environment.')
    from huggingface_hub import snapshot_download
    import torch
    from safetensors.torch import save_file
    path=ROOT/'runtime/skapp/chinese-clip'
    snapshot_download(MODEL,revision=REVISION,local_dir=str(path),allow_patterns=['config.json','preprocessor_config.json','vocab.txt','pytorch_model.bin','README.md'],max_workers=3)
    weights=path/'model.safetensors'
    if not weights.exists():
        state=torch.load(path/'pytorch_model.bin',map_location='cpu',weights_only=True)
        target=path/'model.safetensors.tmp'
        save_file({k:v.contiguous() for k,v in state.items()},target,metadata={'format':'pt'})
        target.replace(weights)
    def digest(p):
        with p.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
    (path/'provenance.json').write_text(json.dumps(dict(model=MODEL,revision=REVISION,weights_sha256=digest(weights),source_weights_sha256=digest(path/'pytorch_model.bin'),conversion='torch.load(weights_only=True) then safetensors'),indent=2)+'\n')
    print('Local model ready. No user content was uploaded.')

if __name__=='__main__':main()
