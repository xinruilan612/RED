"""Package authored documents and read-only verification evidence; never runtime data."""
from pathlib import Path
import hashlib
import json
import zipfile

ROOT = Path(__file__).resolve().parents[1]
NAME = '47191919-AI+软件创新-有迹-文档交付包'


def build():
    evidence = ROOT / 'docs/submission/evidence'
    checks = json.loads((evidence / 'pdf-checks.json').read_text())
    manifest = json.loads((evidence / 'source-manifest.json').read_text())
    files = {}
    for filename, data in checks.items():
        path = ROOT / 'output/pdf' / filename
        assert hashlib.sha256(path.read_bytes()).hexdigest() == data['sha256']
        files[filename] = path
    for path in (ROOT / 'docs/submission').glob('[0-9][0-9]_*.md'):
        files['可编辑正文/' + path.name] = path
    for path in evidence.iterdir():
        if path.is_file():
            files['evidence/' + path.name] = path
    for relative, sha in manifest.items():
        path = ROOT / relative
        assert hashlib.sha256(path.read_bytes()).hexdigest() == sha
        files['核验依据/' + relative] = path
    for path in (ROOT / 'scripts/build_submission_docs.py', ROOT / 'scripts/package_submission.py'):
        files['构建脚本/' + path.name] = path
    readme = '''有迹文档交付包
团队编号：47191919
赛题：AI+软件创新

先阅读“提交清单与待填项.pdf”。四份正式文档位于根目录，配套录制脚本不等于视频成片。
可编辑正文为UTF-8 Markdown；evidence保存实际测试日志与文件校验信息。
核验依据仅收录文档引用的代码和记录，不是完整可安装源码包，不含私有配置或运行数据库。

产品基线：ca8b327；本次产品复验169项通过，新增文档检查后全量174项通过，均无跳过。
本机验证不等同于公网部署或真实模型质量评测。视频、答辩幻灯片、演示交付入口尚需实际完成。
官方网盘模板未成功获取，提交前核对模板封面与固定版式。作品上传截止需以报名系统和赛区通知核实。
本包未上传报名系统或外部网盘，不代表提交成功。
'''
    output = ROOT / 'output' / (NAME + '.zip')
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(NAME + '/请先阅读.txt', readme)
        for relative, path in sorted(files.items()):
            assert not path.name.startswith('.env')
            assert 'runtime' not in path.relative_to(ROOT).parts
            archive.write(path, NAME + '/' + relative)
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        assert sum(n.endswith('.pdf') for n in archive.namelist()) == 6
    print(output)
    print(f'{output.stat().st_size} bytes; {len(files)+1} entries')


if __name__ == '__main__':
    build()
