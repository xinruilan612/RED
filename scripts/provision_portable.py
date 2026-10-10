"""Owner-only local provisioning: one selected DeepSeek key, never the entire .env."""
import argparse
import json
import os
from pathlib import Path


def provision(bundle, key):
    bundle = Path(bundle).resolve()
    if not (bundle / 'build-manifest.json').is_file() or not ((bundle / 'Youji').is_file() or (bundle / 'Youji.exe').is_file()):
        raise ValueError('Not a built portable application')
    if not isinstance(key, str) or not key or len(key) > 4096 or any(c.isspace() for c in key):
        raise ValueError('Missing or invalid DeepSeek credential')
    target = bundle / 'provision.json'
    # Do not overwrite an existing credential or follow a symlink.
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
        json.dump({'schema_version': 1, 'deepseek_api_key': key, 'windtunnel_allow_live': True}, stream)
    return target


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('bundle', type=Path)
    args = parser.parse_args()
    try:
        provision(args.bundle, os.environ.get('DEEPSEEK_API_KEY', ''))
    except (OSError, ValueError):
        raise SystemExit('Provisioning failed; existing files preserved. No credential printed.') from None
    print('Private credential provisioned locally. Do not publish this package.')


if __name__ == '__main__': main()
