"""Owner-only local provisioning: one selected DeepSeek key, never the entire .env."""
import argparse
import json
import hashlib
import os
from pathlib import Path


def private_instructions(manifest):
    platform = manifest.get('platform', '未标记')
    architecture = manifest.get('architecture', '未标记')
    # Describe this bundle, not the provisioning computer or an untested OS.
    systems = {
        'win32': ('Windows', '解压整个文件夹后双击“启动有迹.cmd”（同目录保留Youji.exe、_internal、browser和assets）。', r'%LOCALAPPDATA%\Youji'),
        'darwin': ('macOS', '解压整个文件夹后双击“启动有迹.command”（同目录保留Youji、_internal、browser和assets）。若系统阻止打开，请先核对交付来源，再按macOS针对该文件的打开提示处理；勿关闭全局安全检查。', '~/Library/Application Support/Youji'),
        'linux': ('Linux', '解压tar.gz后在Youji文件夹内打开终端，执行 ./start-youji.sh。若提示无执行权限，执行 chmod +x start-youji.sh Youji 后重试；保留_internal、browser和assets。', '$XDG_DATA_HOME/youji（未设置时为 ~/.local/share/youji）'),
    }
    label, startup, directory = systems.get(platform, ('未标记系统', '请先向交付方核对构建清单，再选择对应系统的启动文件；不要跨系统运行。', '按对应系统用户数据目录保存'))
    return (
        '有迹私有交付包\n'
        f'本包构建系统：{label}；架构：{architecture}。请选择与设备匹配的包，勿将CI构建验收等同于所有系统版本实测。\n'
        + startup + '\n'
        '启动后等待本机浏览器自动打开；无需安装Python、数据库或填写DeepSeek密钥。若未自动打开，请复制启动窗口显示的 http://127.0.0.1:端口 地址到浏览器，勿使用固定旧端口。\n'
        '首次使用创建本机账号，妥善保存一次性恢复码。请保持启动窗口打开；关闭窗口结束API和Worker服务，关闭浏览器标签页不会退出服务。再次启动恢复本机数据。\n'
        'AI创作、读者检查与复审需要联网，费用由交付方预配置的DeepSeek账号承担。离线资料与已确认稿件的导出不调用收费模型。\n'
        '本包包含创作、可选读者检查、改稿复审、单张海报和全文分张导出。实验性SKAPP/ChineseCLIP选题预测未随本包安装，现有Mac独立实验环境不受影响。\n'
        f'默认资料、稿件及历史目录：{directory}；运行日志为该目录下的 launcher.log。若启动失败，先查看该日志并向交付方反馈；不要发送provision.json、数据库、恢复码或完整用户资料。\n'
        '应用文件与用户数据分开保存；卸载应用文件不会删除历史，请按需要自行备份。\n'
        '包内预配置密钥可被持有者读取；仅定向交付，不要公开上传。\n'
    )


def provision(bundle, key):
    bundle = Path(bundle).resolve()
    if not (bundle / 'build-manifest.json').is_file() or not ((bundle / 'Youji').is_file() or (bundle / 'Youji.exe').is_file()):
        raise ValueError('Not a built portable application')
    if not isinstance(key, str) or not key or len(key) > 4096 or any(c.isspace() for c in key):
        raise ValueError('Missing or invalid DeepSeek credential')
    manifest = json.loads((bundle / 'build-manifest.json').read_text(encoding='utf-8'))
    if not isinstance(manifest, dict):
        raise ValueError('Invalid build manifest')
    instructions = private_instructions(manifest)
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
    (bundle / '使用说明.txt').write_text(instructions, encoding='utf-8')
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
