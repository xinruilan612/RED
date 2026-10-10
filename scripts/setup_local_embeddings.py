"""Explicitly install/download the pinned optional local Chinese RAG model.

Run with the project's Python. Never executed implicitly by the application.
Downloads only configuration/tokenizer/text and safetensors, no pickle/code.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
REPO = 'BAAI/bge-small-zh-v1.5'
REVISION = '7999e1d3359715c523056ef9478215996d62a620'
WEIGHTS_SHA256 = '354763b9b1357bc9c44f62c6be2276321081ed2567773608c0d0785b61d5a026'
FILES = ('1_Pooling/config.json','README.md','config.json','config_sentence_transformers.json',
         'model.safetensors','modules.json','sentence_bert_config.json','special_tokens_map.json',
         'tokenizer.json','tokenizer_config.json','vocab.txt')
DESTINATION = ROOT/'runtime/models/bge-small-zh-v1.5'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install-dependencies',action='store_true')
    args = parser.parse_args()
    if args.install_dependencies:
        subprocess.run([sys.executable,'-m','pip','install','-r',str(ROOT/'requirements-rag.txt')],check=True)
    DESTINATION.mkdir(parents=True,exist_ok=True)
    hashes = {}
    for filename in FILES:
        destination = DESTINATION/filename
        destination.parent.mkdir(parents=True,exist_ok=True)
        url = f'https://huggingface.co/{REPO}/resolve/{REVISION}/{filename}'
        temporary = destination.with_suffix(destination.suffix+'.download')
        digest = hashlib.sha256()
        try:
            with urllib.request.urlopen(url,timeout=120) as response, temporary.open('wb') as output:
                size = 0
                while block := response.read(1024*1024):
                    size += len(block)
                    if size > 500_000_000:
                        raise ValueError('Unexpected model file size')
                    output.write(block);digest.update(block)
            if filename=='model.safetensors' and digest.hexdigest()!=WEIGHTS_SHA256:
                raise ValueError('Pinned safetensors checksum mismatch')
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
        hashes[filename] = digest.hexdigest()
        print(filename+' verified download',flush=True)
    manifest = {'repository':REPO,'revision':REVISION,'license':'MIT',
                'source':'https://huggingface.co/'+REPO,'files_sha256':hashes}
    (DESTINATION/'youji-model-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('Local model ready. Restart API/Worker to discover it. No paid inference configured.')


if __name__ == '__main__':
    main()
