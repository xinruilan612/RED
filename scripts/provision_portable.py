"""Owner-only local provisioning: one selected DeepSeek key, never the entire .env."""
import argparse
import json
import hashlib
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
    (bundle / 'private-distribution.json').write_text(json.dumps({
        'schema_version': 1, 'credential_included': True,
        'scope': 'private_judge_delivery',
        'generic_build_manifest_sha256': hashlib.sha256((bundle / 'build-manifest.json').read_bytes()).hexdigest()
    }, indent=2), encoding='utf-8')
    (bundle / '使用说明.txt').write_text(
        '有迹私有交付包：解压后运行启动文件，浏览器会自动打开。无需安装Python、数据库或填写DeepSeek密钥。\n'
        '首次使用创建本机账号；请保持启动窗口打开，关闭窗口结束服务。AI功能需要联网，费用由交付方DeepSeek账号承担。\n'
        '本包包含创作、可选读者检查、改稿复审、单张海报和全文分张导出。实验性SKAPP选题预测未随本包安装。\n'
        '资料与稿件保存在当前系统用户数据目录，卸载应用文件不会删除历史。\n'
        '包内预配置的密钥可被持有者读取；仅定向交付，不要公开上传。\n', encoding='utf-8')
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
