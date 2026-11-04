"""Build consistent source/Windows deliverables from one explicit local commit.

Run from app with --git-dir pointing at the established separate history.
Runtime/data/credentials never enter the archive. Windows execution is untested
on this Mac; package integrity does not claim Windows launch success.
"""
import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
import subprocess
import sys
import zipfile

APP = Path(__file__).resolve().parents[1]
ROOT = APP.parent
sys.path.insert(0, str(APP))
from scripts.package_teacher import _source_allowed, _textual, secret_candidates


def sha(data):
    return hashlib.sha256(data).hexdigest()


def pack(target, entries, commit, prefix):
    manifest = {'source_commit':commit, 'windows_native_tested':False,
                'private_runtime_included':False, 'files':{n:{'bytes':len(d),'sha256':sha(d)} for n,d in sorted(entries.items())}}
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name, data in sorted(entries.items()):
            parts = Path(name).parts
            if Path(name).is_absolute() or '..' in parts or any(p in ('runtime','data','.git','__pycache__') for p in parts):
                raise ValueError('Unsafe member: '+name)
            if name.endswith(('.sqlite','.db','.key','-wal','-shm')):
                raise ValueError('Private member: '+name)
            archive.writestr(prefix+'/'+name,data)
        archive.writestr(prefix+'/DELIVERY_MANIFEST.json',json.dumps(manifest,ensure_ascii=False,indent=2))
    with zipfile.ZipFile(target) as archive:
        if archive.testzip() is not None:
            raise ValueError('ZIP CRC verification failed')
        for name, metadata in manifest['files'].items():
            if sha(archive.read(prefix+'/'+name)) != metadata['sha256']:
                raise ValueError('Member hash mismatch: '+name)
    digest = sha(target.read_bytes())
    target.with_suffix(target.suffix+'.sha256').write_text(digest+'  '+target.name+'\n')
    return {'file':target.name,'bytes':target.stat().st_size,'members':len(entries)+1,'sha256':digest}


def release_names(release_date='20261102', release_label='冲刺验收版'):
    if not re.fullmatch(r'\d{8}',release_date):raise ValueError('release-date须为YYYYMMDD')
    datetime.strptime(release_date,'%Y%m%d')
    if not release_label or re.search(r'[\\/:*?"<>|\x00-\x1f]',release_label) or release_label.endswith((' ','.')):
        raise ValueError('release-label不是安全的Windows文件名')
    legacy=release_date=='20261102' and release_label=='冲刺验收版'
    source='源码与验收成果' if legacy else '有迹-'+release_label+'-源码与验收-'+release_date
    return {'source':source+'.zip','source_prefix':'有迹-冲刺源码与验收' if legacy else source,
            'windows':'有迹-'+release_label+'-Windows-x64-'+release_date+'.zip',
            'windows_prefix':'有迹-'+release_label+'-Windows-x64-'+release_date,
            'bundle':'有迹冲刺开发历史.bundle' if legacy else '有迹'+release_label+'开发历史.bundle'}


def evidence_files(out, legacy=False):
    """Explicit release evidence areas, plus legacy loose documents; never archives."""
    allowed_roots=('01提交文档','02测试与证据','03评审')
    roots=[p for p in out.iterdir() if p.is_file()]
    roots += ([p for p in out.iterdir() if p.is_dir() and not (p/'app'/'backend').exists()] if legacy else [out/name for name in allowed_roots if (out/name).exists()])
    denied_dirs={'app','python','runtime','data','.git','__pycache__','backend','frontend','scripts','tests','04源码'}
    denied_suffixes=('.zip','.bundle','.sha256','.tar','.gz','.7z','.rar','.sqlite','.db','-wal','-shm')
    files=[]
    for root in roots:
        if root.is_symlink():raise ValueError('Evidence symlink: '+str(root))
        candidates=[root] if root.is_file() else sorted(root.rglob('*'))
        for path in candidates:
            relative=path.relative_to(out)
            if path.is_symlink():raise ValueError('Evidence symlink: '+str(relative))
            if not path.is_file():continue
            if any(part.lower() in denied_dirs for part in relative.parts):continue
            lower=path.name.lower()
            if lower.endswith(denied_suffixes) or lower in ('delivery_manifest.json','manifest.json','交付校验.json','sha256sums'):continue
            if not _source_allowed(relative.as_posix()):continue
            files.append(path)
    return sorted(set(files))


def build(git_dir, out, release_date='20261102', release_label='冲刺验收版', *, app=APP, root=ROOT):
    names=release_names(release_date,release_label)
    app,root,out=Path(app).resolve(),Path(root).resolve(),Path(out).resolve()
    if out==app or app in out.parents:raise ValueError('Output必须位于源码目录之外')
    out.mkdir(parents=True,exist_ok=True)
    command=['git','--git-dir='+str(Path(git_dir).resolve()),'--work-tree='+str(app)]
    if subprocess.check_output(command+['status','--porcelain']).strip():
        raise RuntimeError('Commit all intended source changes before release')
    commit=subprocess.check_output(command+['rev-parse','HEAD']).decode().strip()
    tracked=subprocess.check_output(command+['ls-files','-z']).decode().split('\0')
    source={};findings=[]
    for name in filter(None,tracked):
        if not _source_allowed(name) or name.lower().endswith(('.bundle','.sha256')):continue
        path=app/name
        if path.is_symlink() or not path.is_file():raise ValueError(name)
        data=path.read_bytes();source['app/'+name]=data
        if _textual(name,data):findings.extend(secret_candidates('app/'+name,data))
    if findings:raise ValueError('Source credential scan did not pass')
    evidence=evidence_files(out,legacy=release_date=='20261102' and release_label=='冲刺验收版')
    for path in evidence:
        relative=path.relative_to(out).as_posix();data=path.read_bytes()
        if _textual(relative,data):findings.extend(secret_candidates(relative,data))
        source['验收成果/'+relative]=data
    if findings:raise ValueError('Evidence credential scan did not pass')
    bundle=out/names['bundle']
    if bundle.exists():bundle.unlink()
    subprocess.run(command+['bundle','create',str(bundle),'--all'],check=True,capture_output=True)
    subprocess.run(command+['bundle','verify',str(bundle)],check=True,capture_output=True)
    source[bundle.name]=bundle.read_bytes()
    portable=dict(source);runtime={}
    for name in ('一键启动.cmd','先读我.txt','示例产品资料.txt'):portable[name]=(root/name).read_bytes()
    for path in sorted((root/'python').rglob('*')):
        if path.is_symlink():raise ValueError('Runtime symlink')
        if path.is_file():
            name=path.relative_to(root).as_posix();portable[name]=path.read_bytes();runtime[name]=sha(portable[name])
    if 'python/python.exe' not in portable:raise ValueError('Missing original Windows runtime')
    reports=[pack(out/names['source'],source,commit,names['source_prefix']),
             pack(out/names['windows'],portable,commit,names['windows_prefix'])]
    with zipfile.ZipFile(out/names['source']) as a,zipfile.ZipFile(out/names['windows']) as b:
        for name,data in source.items():
            if a.read(names['source_prefix']+'/'+name)!=data or b.read(names['windows_prefix']+'/'+name)!=data:
                raise ValueError('Source/Windows mismatch: '+name)
        for name,digest in runtime.items():
            if sha(b.read(names['windows_prefix']+'/'+name))!=digest:raise ValueError(name)
    result={'source_commit':commit,'release_date':release_date,'release_label':release_label,
            'archives':reports,'source_entries_compared':len(source),'runtime_files_verified':len(runtime),
            'evidence_files':[{ 'path':p.relative_to(out).as_posix(),'sha256':sha(p.read_bytes())} for p in evidence],
            'secret_candidates':0,'windows_native_tested':False,'checks':['clean_tracked_worktree','git_bundle_verify','zip_crc','every_member_sha256','all_source_bytes_identical','original_runtime_identical','no_runtime_state']}
    (out/'交付校验.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--git-dir',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--release-date',default='20261102')
    parser.add_argument('--release-label',default='冲刺验收版')
    args=parser.parse_args()
    result=build(args.git_dir,args.output,args.release_date,args.release_label)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
