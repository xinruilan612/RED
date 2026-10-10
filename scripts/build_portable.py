"""Build a secret-free native onedir package. Run separately on each target OS."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
FONT_REV = 'f8d157532fbfaeda587e826d4cd5b21a49186f7c'
FONT_FILES = {'NotoSansCJKsc-Regular.otf': 'Sans/OTF/SimplifiedChinese/NotoSansCJKsc-Regular.otf', 'LICENSE': 'Sans/LICENSE'}


def fetch_assets(directory):
    directory.mkdir(parents=True, exist_ok=True)
    for name, source in FONT_FILES.items():
        target = directory / name
        if not target.exists():
            url = f'https://raw.githubusercontent.com/notofonts/noto-cjk/{FONT_REV}/{source}'
            with urllib.request.urlopen(url, timeout=120) as response:
                data = response.read(25_000_000)
            if not data or (name == 'LICENSE' and b'SIL OPEN FONT LICENSE' not in data):
                raise RuntimeError('Font asset/license validation failed')
            target.write_bytes(data)
    return directory


def build(output, assets, browser):
    if not browser.is_dir() or not list(browser.glob('chromium-*')):
        raise RuntimeError('Install the pinned Playwright Chromium into --browser-dir first')
    output.mkdir(parents=True, exist_ok=True)
    work = ROOT / 'runtime/portable-build'
    work.mkdir(parents=True, exist_ok=True)
    args = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--name', 'Youji',
            '--distpath', str(output), '--workpath', str(work / 'work'), '--specpath', str(work), '--paths', str(ROOT)]
    for source, dest in [('frontend', 'frontend'), ('docs/design/design_contract.json', 'docs/design'), ('backend/vendor', 'backend/vendor')]:
        args += ['--add-data', str(ROOT / source) + os.pathsep + dest]
    for package in ['backend', 'langgraph', 'uvicorn']:
        args += ['--collect-submodules', package]
    for package in ['imageio_ffmpeg', 'playwright']:
        args += ['--collect-all', package]
    for package in ['langgraph', 'langchain_core', 'langgraph_checkpoint', 'langgraph_prebuilt', 'langgraph_sdk', 'pydantic', 'pydantic_core']:
        args += ['--copy-metadata', package]
    args += [str(ROOT / 'scripts/portable_launcher.py')]
    subprocess.run(args, check=True, cwd=ROOT)
    bundle = output / 'Youji'
    shutil.copytree(assets, bundle / 'assets/fonts', dirs_exist_ok=True)
    shutil.copytree(browser, bundle / 'browser', dirs_exist_ok=True, symlinks=True)
    if sys.platform == 'darwin':
        starter = bundle / '启动有迹.command'
        starter.write_text('#!/bin/sh\ncd "$(dirname "$0")"\nexec ./Youji\n', encoding='utf-8')
        starter.chmod(0o755)
    elif os.name == 'nt':
        (bundle / '启动有迹.cmd').write_text('@echo off\r\ncd /d "%~dp0"\r\nYouji.exe\r\nif errorlevel 1 pause\r\n', encoding='utf-8')
    else:
        starter = bundle / 'start-youji.sh'
        starter.write_text('#!/bin/sh\ncd "$(dirname "$0")"\nexec ./Youji\n', encoding='utf-8'); starter.chmod(0o755)
    (bundle / '使用说明.txt').write_text('有迹：解压后运行启动文件，自动打开浏览器。请保持启动窗口打开；关闭窗口结束服务。\n首次使用创建本机账号。联网后AI调用由交付方预配的DeepSeek账号承担。资料、稿件和历史保存在本机用户数据目录；卸载应用文件不会删除它们。\n此公共构建不含模型密钥；由项目所有者在本机加入私有provision.json后交付。不要将已配置的私有包公开上传。\n', encoding='utf-8')
    manifest = {'schema_version': 1, 'platform': sys.platform, 'architecture': platform.machine(), 'python': platform.python_version(), 'font_revision': FONT_REV, 'credential_included': False,
                'source_commit': subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(), 'files': {}}
    for file in sorted(bundle.rglob('*')):
        if file.is_file():
            if file.name == '.env' or file.name == 'provision.json' or file.suffix in ('.sqlite', '.db'):
                raise RuntimeError('Sensitive/runtime file present in generic bundle')
            manifest['files'][str(file.relative_to(bundle))] = hashlib.sha256(file.read_bytes()).hexdigest()
    (bundle / 'build-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return bundle


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT / 'runtime/portable-dist')
    parser.add_argument('--browser-dir', type=Path, required=True)
    args = parser.parse_args()
    assets = fetch_assets(ROOT / 'runtime/package-assets/fonts')
    print(build(args.output.resolve(), assets, args.browser_dir.resolve()))


if __name__ == '__main__': main()
