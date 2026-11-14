"""Release tooling fixtures; Windows binaries are opaque bytes, never executed."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile
from scripts.package_sprint_release import build,evidence_files,release_names,sha

class SprintReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.app=self.root/'app';self.app.mkdir()
        self.out=self.root/'output'/'有迹-省赛最终交付-20261103';self.out.mkdir(parents=True)
        self.write(self.app/'backend/api.py','# offline fixture\n')
        self.write(self.app/'frontend/app.js','const fixture=true;\n')
        self.write(self.app/'scripts/teacher_launcher.py','# fixture launcher\n')
        self.write(self.root/'python/python.exe',b'opaque-Windows-fixture\x00')
        self.write(self.root/'python/python312.dll',b'opaque-dll-fixture')
        for name in ('一键启动.cmd','先读我.txt','示例产品资料.txt'):self.write(self.root/name,'offline fixture')
        self.git('init','-q');self.git('add','.')
        self.git('-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','fixture')
        self.write(self.out/'01提交文档/方案.md','方案正文')
        self.write(self.out/'02测试与证据/新证据/验收.log','offline evidence')
        self.write(self.out/'03评审/评分.csv','reviewer,score\n')
    def write(self,path,value):
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(value if isinstance(value,bytes) else value.encode())
    def git(self,*args):return subprocess.run(['git','-C',str(self.app),*args],check=True,capture_output=True)
    def package(self,**extra):return build(self.app/'.git',self.out,'20261103','省赛最终交付',app=self.app,root=self.root,**extra)
    def test_defaults_and_custom_names_are_consistent_and_validated(self):
        old=release_names();self.assertEqual(old['source'],'源码与验收成果.zip')
        self.assertEqual(old['windows'],'有迹-冲刺验收版-Windows-x64-20261102.zip')
        names=release_names('20261103','省赛最终交付')
        self.assertEqual(names['windows'],'有迹-省赛最终交付-Windows-x64-20261103.zip')
        self.assertEqual(names['source'],names['source_prefix']+'.zip')
        for date,label in [('20260230','名称'),('2026-11-03','名称'),('20261103','../bad'),('20261103','bad:label')]:
            with self.assertRaises(ValueError):release_names(date,label)
    def test_build_compares_all_source_bytes_evidence_and_original_runtime(self):
        before={p.name:p.read_bytes() for p in (self.root/'python').iterdir()}
        report=self.package();names=release_names('20261103','省赛最终交付')
        self.assertFalse(report['windows_native_tested'])
        self.assertEqual(len(report['evidence_files']),3)
        with zipfile.ZipFile(self.out/names['source']) as source,zipfile.ZipFile(self.out/names['windows']) as windows:
            manifest=json.loads(source.read(names['source_prefix']+'/DELIVERY_MANIFEST.json'))
            for name,metadata in manifest['files'].items():
                a=source.read(names['source_prefix']+'/'+name);b=windows.read(names['windows_prefix']+'/'+name)
                self.assertEqual(a,b);self.assertEqual(sha(a),metadata['sha256'])
            self.assertIn(names['source_prefix']+'/验收成果/02测试与证据/新证据/验收.log',source.namelist())
            for name,original in before.items():self.assertEqual(windows.read(names['windows_prefix']+'/python/'+name),original)
        self.assertEqual(before,{p.name:p.read_bytes() for p in (self.root/'python').iterdir()})
    def test_repeated_build_does_not_nest_old_archives_manifests_or_expanded_source(self):
        names=release_names('20261103','省赛最终交付')
        self.write(self.out/'04源码/app/backend/api.py','must-not-recurse')
        self.write(self.out/'01提交文档/旧材料.zip',b'archive-fixture')
        self.write(self.out/'02测试与证据/MANIFEST.json','{"stale":true}')
        self.write(self.out/'02测试与证据/旧.bundle',b'bundle-fixture')
        self.write(self.out/'02测试与证据/app/backend/copied.py','expanded-source-fixture')
        first=self.package();second=self.package()
        self.assertEqual(first['source_entries_compared'],second['source_entries_compared'])
        self.assertEqual(first['evidence_files'],second['evidence_files'])
        with zipfile.ZipFile(self.out/names['source']) as archive:
            members=archive.namelist();self.assertFalse(any(n.endswith('.zip') for n in members))
            self.assertFalse(any('04源码' in n or 'copied.py' in n or '旧.bundle' in n or 'MANIFEST.json' in n and not n.endswith('DELIVERY_MANIFEST.json') for n in members))
            self.assertEqual(sum(n.endswith('.bundle') for n in members),1)
    def test_dirty_source_or_evidence_symlink_is_refused(self):
        self.write(self.app/'frontend/app.js','uncommitted change')
        with self.assertRaises(RuntimeError):self.package()
        self.git('checkout','--','frontend/app.js')
        (self.out/'03评审/linked.txt').symlink_to(self.app/'backend/api.py')
        with self.assertRaises(ValueError):evidence_files(self.out)
    def test_legacy_evidence_subfolders_remain_supported_without_expanded_packages(self):
        self.write(self.out/'评价工具/原始表.csv','fixture')
        self.write(self.out/'旧展开源码/app/backend/api.py','expanded source')
        new={str(p.relative_to(self.out)) for p in evidence_files(self.out)}
        old={str(p.relative_to(self.out)) for p in evidence_files(self.out,legacy=True)}
        self.assertNotIn('评价工具/原始表.csv',new)
        self.assertIn('评价工具/原始表.csv',old)
        self.assertFalse(any('旧展开源码' in path for path in old))

    def test_output_inside_source_is_refused(self):
        with self.assertRaises(ValueError):build(self.app/'.git',self.app/'nested',app=self.app,root=self.root)

if __name__=='__main__':unittest.main()
