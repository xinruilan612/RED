"""Export original project files and readable Git history for process review."""
import argparse
import hashlib
import json
import re
import subprocess
import zipfile
from pathlib import Path

from scripts.package_windtunnel import allowed_path, SECRET_PATTERNS

ROOT = Path(__file__).resolve().parents[1]
PREFIX = '有迹-项目过程原始材料'
TEXT_SUFFIXES = {'.py', '.md', '.json', '.csv', '.txt', '.log', '.snapshot',
                 '.html', '.svg', '.mmd', '.js', '.cjs', '.css', '.cmd'}


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), '-c', 'core.quotePath=false',
                           *args], check=True, capture_output=True).stdout


def eligible(name):
    return allowed_path(name) and (Path(name).suffix.lower() in TEXT_SUFFIXES
                                   or name in {'.env.example', '.gitignore'})


def sanitize(data):
    """Replace credential-shaped values, including in deleted historical lines."""
    count = 0
    for pattern in SECRET_PATTERNS:
        data, changed = pattern.subn(b'[REDACTED_CREDENTIAL]', data)
        count += changed
    # A header alone is insufficient: remove the entire private-key body.
    data, changed = re.subn(
        rb'\[REDACTED_CREDENTIAL\][\r\n]+[A-Za-z0-9+/=\r\n]+-----END '
        rb'(?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
        b'[REDACTED_PRIVATE_KEY]', data)
    return data, count + changed


def build(output, root=ROOT, extras=(), verification=None):
    root, output = Path(root).resolve(), Path(output).resolve()
    files, redactions, exclusions = {}, {}, []

    def include(name, data):
        clean, count = sanitize(data)
        files[name] = clean
        if count:
            redactions[name] = count

    tracked = git(root, 'ls-files', '-z').decode().split('\0')
    for name in sorted((set(tracked) | set(extras)) - {''}):
        if not eligible(name):
            exclusions.append(name)
            continue
        path = root / name
        if not path.is_file() or path.is_symlink() or any(
                parent.is_symlink() for parent in path.parents if parent != root.parent):
            exclusions.append(name)
            continue
        if not path.resolve().is_relative_to(root):
            raise ValueError('Source escapes project')
        include('项目原文件/' + name, path.read_bytes())

    commits = git(root, 'rev-list', '--all', '--reverse', '--topo-order').decode().splitlines()
    fmt = 'commit %H%nparents %P%nauthor %an%nDate %aI%n%n%B'
    include('Git历史/提交记录.txt', git(root, 'log', '--all', '--reverse', '--topo-order',
                                       '--date=iso-strict', '--format=' + fmt, '--stat'))
    for index, commit in enumerate(commits, 1):
        # Include safe paths that were removed by this commit as well.
        changed = git(root, 'diff-tree', '--root', '-m', '--no-commit-id',
                      '--name-only', '-r', '-z', commit).decode().split('\0')
        paths = sorted({name for name in changed if name and eligible(name)})
        if paths:
            patch = git(root, 'show', '-m', '--format=' + fmt, '--no-ext-diff',
                        '--no-textconv', commit, '--', *paths)
        else:
            patch = git(root, 'show', '-s', '--format=' + fmt, commit)
        include(f'Git历史/逐次改动/{index:03d}-{commit[:12]}.patch', patch)

    revision = git(root, 'rev-parse', 'HEAD').decode().strip()
    status = git(root, 'status', '--porcelain=v1').decode()
    include('Git历史/打包时工作区状态.txt', status.encode())
    if verification is not None:
        include('本次打包验证.txt', Path(verification).read_bytes())
    readme = f'''有迹：项目过程原始材料
打包基线 HEAD：{revision}
Git 范围：当前仓库所有可达分支，共 {len(commits)} 个去重提交。

本包回应“给我们看一点你做事的过程”，保留现有文件与历史，不补写实验或聊天。
快速阅读：
1. Git历史/提交记录.txt 与逐次改动/*.patch：版本迭代及修复过程。
2. 项目原文件/docs/IMPLEMENTATION_STATUS.md：阶段进度与实现边界。
3. 项目原文件/docs/WEB_DEMO_VALIDATION.md：原始验证与失败记录。
4. 项目原文件/docs/evidence/2026-09-20-outline-fix.json：真实提纲失败与修复记录。
5. 项目原文件/docs/design/ 与 docs/research/：设计草稿、迁移取舍、调研。
6. 项目原文件/docs/submission/evidence/ 与 docs/windtunnel/evidence/：历史测试日志与快照。
7. 项目原文件/backend/、frontend/、tests/：实际源码与回归用例。

历史日志按原有版本、日期解释；模型替身测试、模拟报告不能作为真实模型质量或账号增长证据。
风洞评测模板为空表/匿名编号，不表示完成真人试验。录制脚本不是视频。
仓库未保存可直接分享的完整真实用户聊天，本包未添加私有聊天、数据库或账号资料。
Git 为可读日志和文本补丁导出，非可还原所有对象的 .git 仓库或 bundle。
未包含 .env、runtime、.git 配置、数据库、上传资料、缓存及已有二进制交付包。
凭据形态值已脱敏；精确路径和次数见 MATERIAL_MANIFEST.json。其余文件按原样保留。
源码以逐文件哈希为准；基线提交与打包时未提交状态均明确记录。
本包只在本地生成，尚未上传任何平台。本次检查范围见“本次打包验证.txt”（若提供）。
'''
    include('请先阅读.txt', readme.encode())
    manifest = {
        'format': 1, 'base_commit': revision, 'git_commit_count': len(commits),
        'history_scope': 'all reachable refs; readable text patches, not a Git bundle',
        'working_tree_status': status, 'redactions': redactions,
        'excluded_current_paths': exclusions,
        'files': {name: {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                  for name, data in sorted(files.items())},
    }
    files['MATERIAL_MANIFEST.json'] = (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode()
    if any(output == (root / name).resolve() for name in tracked if name):
        raise ValueError('Output would overwrite a tracked source')
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + '.partial')
    try:
        with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, data in sorted(files.items()):
                archive.writestr(PREFIX + '/' + name, data)
        with zipfile.ZipFile(temporary) as archive:
            if archive.testzip() is not None:
                raise ValueError('Archive integrity failure')
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix('.zip.sha256').write_text(digest + '  ' + output.name + '\n')
    return {'archive': str(output), 'entries': len(files), 'commits': len(commits),
            'redacted_files': len(redactions), 'bytes': output.stat().st_size, 'sha256': digest}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'output/有迹-项目过程原始材料.zip')
    parser.add_argument('--verification', type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.output, verification=args.verification), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
