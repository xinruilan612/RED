"""Verify the published source snapshot without network or model calls."""
import hashlib
import json
from pathlib import Path


def verify(root):
    root = Path(root).resolve()
    manifest = json.loads((root / 'SOURCE_MANIFEST_20261105.json').read_text(encoding='utf-8'))
    for name, expected in manifest['files'].items():
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Unsafe manifest path')
        path = root / relative
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError('Unsafe source file')
        data = path.read_bytes()
        if len(data) != expected['bytes'] or hashlib.sha256(data).hexdigest() != expected['sha256']:
            raise ValueError('Source hash mismatch: ' + name)
    return len(manifest['files'])


if __name__ == '__main__':
    print('Verified source files:', verify(Path(__file__).resolve().parents[1]))
