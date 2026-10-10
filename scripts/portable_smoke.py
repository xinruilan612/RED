"""Validate a real packaged executable offline. Driver Python is CI-only, not user setup."""
import argparse
import base64
import hashlib
import http.cookiejar
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
import uuid
import zipfile


def ensure(value):
    if not value:
        raise RuntimeError('Packaged smoke acceptance check failed.')


def pdf_fixture():
    # Small valid text PDF assembled with stdlib; tests need no external driver packages.
    parts=[b'<< /Type /Catalog /Pages 2 0 R >>', b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>', b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>', b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    text=b'BT /F1 12 Tf 20 200 Td (Offline portable PDF evidence.) Tj ET'
    parts.append(b'<< /Length '+str(len(text)).encode()+b' >>\nstream\n'+text+b'\nendstream')
    raw=b'%PDF-1.4\n';offsets=[0]
    for i,part in enumerate(parts,1):offsets.append(len(raw));raw+=str(i).encode()+b' 0 obj\n'+part+b'\nendobj\n'
    start=len(raw);raw+=b'xref\n0 6\n0000000000 65535 f \n'
    for offset in offsets[1:]:raw+=f'{offset:010d} 00000 n \n'.encode()
    return raw+b'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n'+str(start).encode()+b'\n%%EOF\n'


def docx_fixture():
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w') as archive:
        archive.writestr('[Content_Types].xml','<Types/>')
        archive.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>中文离线资料：冷水清洗并自然晾干。</w:t></w:r></w:p></w:body></w:document>')
    return output.getvalue()


class HTTP:
    def __init__(self,origin):
        self.origin=origin;self.csrf=None
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def request(self,path,data=None):
        headers={}
        if data is not None:headers.update({'Content-Type':'application/json','Origin':self.origin,'X-CSRF-Token':self.csrf or ''})
        request=urllib.request.Request(self.origin+path,None if data is None else json.dumps(data,ensure_ascii=False).encode(),headers)
        with self.opener.open(request,timeout=30) as response:
            raw=response.read();mime=response.headers.get('Content-Type','')
        if path.endswith('.js'):return raw,mime
        value=json.loads(raw)
        if isinstance(value,dict) and value.get('csrf'):self.csrf=value['csrf']
        return value


def command(executable,extra):
    return [str(executable),*extra]


def start(executable,data,config,ready,log):
    ready.unlink(missing_ok=True)
    process=subprocess.Popen(command(executable,['--no-browser','--data-dir',str(data),'--config-path',str(config),'--ready-file',str(ready)]),cwd=str(data.parent),stdout=log,stderr=subprocess.STDOUT)
    deadline=time.monotonic()+60
    while not ready.exists():
        if process.poll() is not None or time.monotonic()>deadline:
            stop(process);raise RuntimeError('Packaged API/worker did not become ready; inspect smoke launcher log.')
        time.sleep(.1)
    packet=json.loads(ready.read_text())
    if not packet.get('ready') or not packet['origin'].startswith('http://127.0.0.1:'):
        stop(process);raise RuntimeError('Invalid packaged readiness report.')
    return process,HTTP(packet['origin'])


def stop(process):
    if process.poll() is None:process.terminate()
    try:process.wait(timeout=15)
    except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)


def run(executable,output):
    executable=Path(executable).absolute();output=Path(output).absolute();output.mkdir(parents=True,exist_ok=True)
    checks={};process=None
    with tempfile.TemporaryDirectory(prefix='youji-packaged-smoke-') as folder:
        root=Path(folder);data=root/'user';data.mkdir();config=root/'empty-provision.json';ready=root/'ready.json'
        config.write_text('{"schema_version":1,"deepseek_api_key":"","windtunnel_allow_live":false}')
        # Run actual executable from a fresh unrelated cwd. Never borrow repository assets or env.
        with (output/'launcher-smoke.log').open('w') as log:
            try:
                process,http=start(executable,data,config,ready,log)
                ensure(http.request('/health')['database']=='sqlite')
                session=http.request('/api/session');ensure(session['provider']['ready'] is False)
                checks['fresh_sqlite_api_and_worker']=True
                for asset in ('app.js','auth.js','knowledge.js','windtunnel.js','media_exports.js'):
                    raw,mime=http.request('/'+asset);ensure(raw and ('javascript' in mime))
                checks['static_javascript_mime']=True
                username='smoke_'+uuid.uuid4().hex[:14];password='PortableSmokeA1'
                http.request('/api/auth/register',{'username':username,'password':password})
                http.request('/api/auth/logout',{});http.request('/api/session')
                http.request('/api/auth/login',{'username':username,'password':password})
                checks['register_logout_login_csrf']=True
                state=http.request('/api/operations')
                profile={k:'' for k in ('positioning','audience','tone','pillars','goal','resources','banned')};profile.update(positioning='离线合成验收',weekly_frequency=3)
                state=http.request('/api/operations',{'action':'save_account','payload':{'id':'','name':'便携测试账号','platform':'xiaohongshu','profile':profile},'version':state['version'],'key':uuid.uuid4().hex})
                account=next(a for a in state['accounts'] if a['name']=='便携测试账号')
                docs=[]
                for title,fields in [('TXT',{'text':'纯棉衬衫使用冷水清洗，不承诺防皱效果。'}),('PDF',{'filename':'test.pdf','file_base64':base64.b64encode(pdf_fixture()).decode()}),('DOCX',{'filename':'test.docx','file_base64':base64.b64encode(docx_fixture()).decode()})]:
                    doc=http.request('/api/knowledge',{'account_id':account['id'],'title':'合成离线'+title,**fields});docs.append(doc)
                    detail=http.request('/api/knowledge/'+doc['id']+'?'+urllib.parse.urlencode({'account_id':account['id']}))
                    ensure(detail['chunks'])
                    expected={'TXT':'冷水','PDF':'Offline portable','DOCX':'中文离线资料'}[title]
                    ensure(expected in ''.join(c['text'] for c in detail['chunks']))
                checks['txt_pdf_docx_frozen_http_parsers']=True
                found=http.request('/api/knowledge/retrieve',{'account_id':account['id'],'query':'纯棉冷水'});ensure(found['sources'])
                stop(process);process,http=start(executable,data,config,ready,log)
                http.request('/api/session');http.request('/api/auth/login',{'username':username,'password':password})
                state=http.request('/api/operations');ensure(any(a['id']==account['id'] for a in state['accounts']))
                listing=http.request('/api/knowledge?'+urllib.parse.urlencode({'account_id':account['id']}));ensure(len(listing)==3)
                checks['restart_account_and_documents_persist']=True
                for doc in docs:http.request('/api/knowledge/'+doc['id']+'/delete',{'account_id':account['id'],'version':doc['version']})
                ensure(http.request('/api/knowledge?'+urllib.parse.urlencode({'account_id':account['id']}))==[])
                checks['document_delete']=True
            finally:
                if process is not None:stop(process)
        media=output/'offline-media'
        result=subprocess.run(command(executable,['--service','self-test','--self-test-output',str(media)]),cwd=root,capture_output=True,timeout=180)
        (output/'offline-media-smoke.log').write_bytes(result.stdout+result.stderr)
        if result.returncode:raise RuntimeError('Packaged offline media self-test failed; no model was called.')
        report=json.loads((media/'self-test-report.json').read_text());ensure(report['paid_model_calls']==0 and report['production_writes'] is False)
        ensure(all(report['checks'][name]['valid'] for name in ('pillow','chromium','ffmpeg')))
        checks['packaged_chinese_pillow_chromium_ffmpeg']=True
    report={'schema_version':1,'executable_sha256':hashlib.sha256(executable.read_bytes()).hexdigest(),'fixture':'synthetic_offline_new_temporary_user_space','paid_model_calls':0,'checks':checks,'account_delete':'unsupported_by_existing_HTTP_contract','user_python_requirement':False,'driver_python':'CI/test harness only'}
    (output/'portable-smoke-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    return report


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--executable',required=True);parser.add_argument('--output',required=True);args=parser.parse_args()
    try:
        run(args.executable,args.output);print('Packaged offline smoke passed; no paid model calls.');return 0
    except Exception as error:
        print('Packaged smoke failed ('+type(error).__name__+'); inspect the local smoke logs.');return 1

if __name__=='__main__':raise SystemExit(main())
