"""Versioned design workflow acceptance; model doubles are labelled explicitly."""
import base64
from copy import deepcopy
from dataclasses import asdict
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4
from PIL import Image
from backend import studio, studio_vision
from backend.contracts import DomainError
from backend.migrations import upgrade
from backend.model_router import Calls
from backend.store import Store
from backend.workflow import digest
from tests.test_media_exports import fixture


def image_data():
    buf=BytesIO(); Image.new('RGB',(1080,1440),'#faf0e0').save(buf,format='PNG')
    return 'data:image/png;base64,'+base64.b64encode(buf.getvalue()).decode()

PNG=image_data()

def fake_preview(run,template='xhs-e',options=None):
    return {'width':1080,'height':1440,'design_hash':digest({'template':template,'options':options}), 'pages':[{'name':'01.png','data_url':PNG,'text_blocks':['fixture text'],'elements':[{'id':'title','type':'text','bounds':{'x':50,'y':50,'width':900,'height':150}},{'id':'image','type':'image','bounds':{'x':50,'y':250,'width':900,'height':600}}]} for _ in range(2)]}


class StudioTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name)/'db.sqlite'); self.prepare()

    def prepare(self):
        upgrade(self.store); self.run=fixture('持久化测试正文')
        with self.store.connect() as db: db.execute('INSERT INTO runs(id,owner,payload) VALUES(?,?,?)',(self.run.run_id,self.run.owner_id,json.dumps(asdict(self.run))))
        patcher=patch('backend.studio.preview_run',side_effect=fake_preview); self.preview=patcher.start(); self.addCleanup(patcher.stop)
        self.state=self.action('init')['state']

    def data(self,action,**extra):
        return {'action':action,'draft_ref':self.run.accepted_ref,'content_hash':self.run.acceptance['content_hash'],'idempotency_key':uuid4().hex,'expected_revision':getattr(self,'state',{}).get('revision',0),**extra}

    def action(self,action,**extra):
        result=studio.mutate(self.store,self.run.owner_id,self.run.run_id,self.data(action,**extra)); self.state=result['state']; return result

    def edit(self,scale=1.1):
        return self.action('edit',operations=[{'page_index':0,'element_id':'image','changes':{'scale':scale}},{'page_index':0,'element_id':'title','changes':{'dy':-15}}])

    def test_initial_layout_accepts_structure_but_not_inline_assets(self):
        other=fixture()
        with self.store.connect() as db: db.execute('INSERT INTO runs(id,owner,payload) VALUES(?,?,?)',(other.run_id,other.owner_id,json.dumps(asdict(other))))
        data=self.data('init',draft_ref=other.accepted_ref,content_hash=other.acceptance['content_hash'],options={'studio':{'pages':{'0':{'layout':'hero'}}}})
        result=studio.mutate(self.store,other.owner_id,other.run_id,data)
        self.assertEqual(result['state']['current']['options']['studio']['pages']['0']['layout'],'hero')
        third=fixture()
        with self.store.connect() as db: db.execute('INSERT INTO runs(id,owner,payload) VALUES(?,?,?)',(third.run_id,third.owner_id,json.dumps(asdict(third))))
        with self.assertRaises(DomainError): studio.mutate(self.store,third.owner_id,third.run_id,{**data,'idempotency_key':uuid4().hex,'options':{'studio':{'pages':{},'assets':{'custom':PNG}}}})

    def test_roundtrip_undo_redo_accept_and_reconnect(self):
        original=deepcopy(self.state['current']); candidate=self.edit()['state']['current']
        self.assertTrue(self.state['has_pending']); self.assertTrue(self.state['can_undo'])
        self.action('undo'); self.assertEqual(self.state['current'],original); self.assertTrue(self.state['can_redo'])
        self.action('redo'); self.assertEqual(self.state['current'],candidate)
        self.action('accept'); self.assertFalse(self.state['has_pending'])
        fresh=Store(self.store.path)
        self.assertEqual(studio.read(fresh,self.run.owner_id,self.run.run_id)['state'],self.state)
        self.assertEqual(fresh.get(self.run.run_id,self.run.owner_id).drafts,self.run.drafts)

    def test_invalid_combination_and_failed_renderer_are_atomic(self):
        baseline=deepcopy(self.state)
        with self.assertRaises(DomainError): self.action('edit',operations=[{'page_index':0,'element_id':'title','changes':{'dy':-15}},{'page_index':0,'element_id':'image','changes':{'scale':3}}])
        self.assertEqual(studio.read(self.store,self.run.owner_id,self.run.run_id)['state'],baseline)
        with patch('backend.studio.preview_run',side_effect=RuntimeError('renderer unavailable')):
            with self.assertRaises(RuntimeError): self.edit()
        self.assertEqual(studio.read(self.store,self.run.owner_id,self.run.run_id)['state'],baseline)

    def test_owner_revision_snapshot_and_idempotency(self):
        with self.assertRaises(DomainError): studio.read(self.store,'other',self.run.run_id)
        data=self.data('edit',operations=[{'page_index':0,'layout':'hero'}]); first=studio.mutate(self.store,self.run.owner_id,self.run.run_id,data)
        self.assertEqual(studio.mutate(self.store,self.run.owner_id,self.run.run_id,data),first)
        for change in ({'expected_revision':999,'idempotency_key':uuid4().hex},{'content_hash':'stale','idempotency_key':uuid4().hex},{'operations':[{'page_index':0,'layout':'compare'}]}):
            with self.assertRaises(DomainError): studio.mutate(self.store,self.run.owner_id,self.run.run_id,{**data,**change})

    def test_late_model_result_cannot_overwrite_newer_manual_edit(self):
        def model(*a,**kw):
            self.action('edit',operations=[{'page_index':1,'layout':'compare'}])
            return {'operations':[{'page_index':0,'element_id':'image','changes':{'scale':1.2}}],'unsupported':False,'reason':'double','observation':'double','call_id':'fixture'}
        with patch.object(Calls,'invoke_studio_vision',side_effect=model):
            with self.assertRaises(DomainError) as caught: self.action('edit',feedback='放大这张图',page_index=0,element_id='image')
        self.assertEqual(caught.exception.code,'VERSION_CONFLICT')
        current=studio.read(self.store,self.run.owner_id,self.run.run_id)['state']
        self.assertEqual(current['current']['options']['studio']['pages'],{'1':{'layout':'compare'}})
        self.assertEqual(current['messages'],[])

    def test_asset_bytes_not_repeated_in_history_or_commands_and_replay(self):
        self.action('asset',asset={'name':'产品照片','role':'product','data_url':PNG}); asset=self.state['assets'][0]
        edit=self.data('edit',operations=[{'page_index':1,'element_id':'image','changes':{'asset_id':asset['id']}}])
        response=studio.mutate(self.store,self.run.owner_id,self.run.run_id,edit)
        self.assertEqual(studio.mutate(self.store,self.run.owner_id,self.run.run_id,edit),response)
        with self.store.connect() as db:
            session=json.loads(db.execute('SELECT payload FROM studio_sessions').fetchone()[0])
            commands=db.execute('SELECT response FROM studio_commands').fetchall()
        self.assertNotIn('data:image',json.dumps(session['history']))
        self.assertTrue(all('data:image' not in row[0] for row in commands))
        self.assertTrue(any(asset['id'] in c.kwargs.get('options',{}).get('studio',{}).get('assets',{}) for c in self.preview.call_args_list))

    def test_export_uses_accepted_and_rechecks_revision(self):
        self.edit(); data={k:v for k,v in self.data('accept').items() if k in ('draft_ref','content_hash','expected_revision')}
        with patch('backend.studio.export_run') as exporter:
            with self.assertRaises(DomainError): studio.export(self.store,self.run.owner_id,self.run.run_id,data)
            exporter.assert_not_called()
        self.action('accept'); data['expected_revision']=self.state['revision']
        with patch('backend.studio.export_run',return_value=(b'zip','application/zip','cards.zip')) as exporter:
            self.assertEqual(studio.export(self.store,self.run.owner_id,self.run.run_id,data)[0],b'zip')
            self.assertEqual(exporter.call_args.kwargs['options'],studio._hydrated(self.state['accepted'],self.state['assets'])['options'])

    def test_noop_proposal_is_reported_without_duplicate_history(self):
        self.edit(.9)
        before=deepcopy(self.state)
        value={'operations':[{'page_index':0,'element_id':'image','changes':{'scale':.9}}],'unsupported':False,'reason':'模型错误声称再缩小','observation':'图像','call_id':'fixture'}
        with patch.object(Calls,'invoke_studio_vision',return_value=value): self.action('edit',feedback='再小一点',page_index=0,element_id='image')
        self.assertFalse(self.state['last_edit_changed']); self.assertIn('画布未变化',self.state['messages'][-1]['text'])
        self.assertEqual(self.state['messages'][-1]['operations'],[])
        self.action('undo'); self.assertFalse(self.state['has_pending'])

    def test_background_opacity_truthful_response_and_undo_redo(self):
        original=deepcopy(self.state['current'])
        operations=[{'page_index':0,'element_id':'image','changes':{'placement':'background'}},{'page_index':0,'element_id':'title','changes':{'opacity':.5}},{'page_index':0,'element_id':'body','changes':{'opacity':.5}}]
        value={'operations':operations,'unsupported':False,'reason':'已发布并生成视频','observation':'不存在的观察','call_id':'fixture'}
        with patch.object(Calls,'invoke_studio_vision',return_value=value): self.action('edit',feedback='把产品图作为背景图，文字半透明',page_index=0,element_id='image')
        message=self.state['messages'][-1]
        self.assertIn('铺满画布的背景图',message['text']); self.assertIn('不透明度设为 50%',message['text'])
        self.assertNotIn('视频',message['text']); self.assertEqual(message['observation'],'')
        changed=deepcopy(self.state['current'])
        self.action('undo'); self.assertEqual(self.state['current'],original)
        self.action('redo'); self.assertEqual(self.state['current'],changed)

    def test_invalid_new_capability_is_atomic(self):
        baseline=deepcopy(self.state)
        for element,change in [('image',{'placement':'video'}),('title',{'opacity':1.1}),('body',{'opacity':True}),('body',{'opacity':float('nan')}),('image',{'opacity':.5})]:
            with self.subTest(change=change),self.assertRaises(DomainError):
                self.action('edit',operations=[{'page_index':0,'element_id':'image','changes':{'placement':'background'}},{'page_index':0,'element_id':element,'changes':change}])
            self.assertEqual(studio.read(self.store,self.run.owner_id,self.run.run_id)['state'],baseline)

    def test_false_model_background_claim_only_reports_actual_color(self):
        value={'operations':[{'page_index':0,'element_id':'image','changes':{'scale':1}},{'page_index':0,'element_id':'body','changes':{'color':'#d0d0d0'}}],'unsupported':False,'reason':'已经设为背景并半透明','observation':'图片已作为背景','call_id':'fixture'}
        with patch.object(Calls,'invoke_studio_vision',return_value=value): self.action('edit',feedback='产品图作为背景，文字半透明',page_index=0,element_id='image')
        message=self.state['messages'][-1]
        self.assertIn('颜色设为 #d0d0d0',message['text']); self.assertNotIn('半透明',message['text']); self.assertNotIn('背景',message['text'])
        self.assertEqual(message['observation'],'')

    def test_unsupported_is_persisted_as_explanation_without_change(self):
        original=deepcopy(self.state['current'])
        value={'operations':[],'unsupported':True,'reason':'请返回稿件编辑并重新审核','observation':'看见标题','call_id':'fixture'}
        with patch.object(Calls,'invoke_studio_vision',return_value=value): self.action('edit',feedback='改标题内容',page_index=0,element_id='title')
        self.assertEqual(self.state['current'],original); self.assertFalse(self.state['has_pending']); self.assertEqual(len(self.state['messages']),2)

    def test_authenticated_http_csrf_and_export_contract(self):
        from fastapi.testclient import TestClient
        from backend.api import create_app
        from backend.provider import Config
        app=create_app(self.store,Config(),origin='http://testserver',invite='')
        with TestClient(app) as client:
            token=client.get('/api/session').json()['csrf']
            registered=client.post('/api/auth/register',json={'username':'studio_http','password':'Studio-Test-2026'},headers={'Origin':'http://testserver','X-CSRF-Token':token})
            self.assertEqual(registered.status_code,200,registered.text)
            token=registered.json()['csrf']; owner=app.state.auth.session(client.cookies.get('youji_session'))['owner']
            run=fixture(); run.owner_id=owner
            with self.store.connect() as db: db.execute('INSERT INTO runs(id,owner,payload) VALUES(?,?,?)',(run.run_id,owner,json.dumps(asdict(run))))
            path='/api/runs/'+run.run_id+'/studio'
            self.assertIsNone(client.get(path).json()['state'])
            data={'action':'init','draft_ref':run.accepted_ref,'content_hash':run.acceptance['content_hash'],'idempotency_key':uuid4().hex}
            self.assertEqual(client.post(path,json=data).status_code,403)
            headers={'Origin':'http://testserver','X-CSRF-Token':token}
            initialized=client.post(path,json=data,headers=headers)
            self.assertEqual(initialized.status_code,200,initialized.text)
            self.assertEqual(client.get('/api/runs/'+self.run.run_id+'/studio').status_code,404)
            export={'draft_ref':run.accepted_ref,'content_hash':run.acceptance['content_hash'],'expected_revision':0,'kind':'images'}
            with patch('backend.studio.export_run',return_value=(b'archive','application/zip','cards.zip')):
                response=client.post(path+'/export',json=export,headers=headers)
            self.assertEqual(response.status_code,200,response.text); self.assertEqual(response.content,b'archive')
            self.assertIn('attachment',response.headers['content-disposition'])

    def test_rejected_parsed_model_response_preserves_usage_and_audit(self):
        rejected={'operations':[{'page_index':0,'element_id':'image','changes':{'asset_id':'missing'}}],'unsupported':False,'observation':'照片','reason':'修改','model':studio_vision.MODEL,'input_tokens':321,'output_tokens':45}
        with self.assertRaises(DomainError):
            Calls.invoke_studio_vision(self.store,self.run,fake_preview(self.run),self.state,'缩小',0,adapter=lambda *args:rejected)
        with self.store.connect() as db: row=db.execute('SELECT status,response_json,input_tokens,output_tokens FROM studio_model_calls').fetchone()
        self.assertEqual(row[0],'failed'); self.assertEqual(json.loads(row[1]),rejected); self.assertEqual(tuple(row[2:]),(321,45))

    def test_local_audit_image_context_and_usage_unknown(self):
        self.action('asset',asset={'name':'风格','role':'reference','data_url':PNG})
        preview=fake_preview(self.run)
        def adapter(context,images):
            self.assertEqual(len(images),3); self.assertEqual(context['selected']['element_id'],'image')
            self.assertEqual([s['role'] for s in context['image_sources']],['canvas','selection','reference'])
            self.assertTrue(all(base64.b64decode(v).startswith(b'\x89PNG') for v in images))
            return {'operations':[{'page_index':0,'element_id':'image','changes':{'scale':1.1}}],'unsupported':False,'observation':'图像','reason':'放大','model':studio_vision.MODEL,'input_tokens':10,'output_tokens':20}
        Calls.invoke_studio_vision(self.store,self.run,preview,self.state,'放大',0,'image',{'x':50,'y':250,'width':100,'height':100},adapter=adapter,reference_asset_id=self.state['assets'][0]['id'])
        def failure(*a): raise RuntimeError('private secret')
        with self.assertRaises(DomainError): Calls.invoke_studio_vision(self.store,self.run,preview,self.state,'放大',0,adapter=failure)
        with self.store.connect() as db: rows=db.execute('SELECT status,input_tokens,output_tokens,input_json,error FROM studio_model_calls ORDER BY started').fetchall()
        self.assertEqual(tuple(rows[0][:3]),('succeeded',10,20)); self.assertEqual(tuple(rows[1][:3]),('failed',None,None))
        self.assertNotIn('data:image',rows[0][3]); self.assertNotIn('private',rows[1][4])


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'),'requires actual PostgreSQL')
class PostgresStudioTests(StudioTests):
    def setUp(self):
        import psycopg
        self.base=os.environ['TEST_DATABASE_URL']; self.schema='youji_studio_'+uuid4().hex
        with psycopg.connect(self.base,autocommit=True) as db: db.execute('CREATE SCHEMA '+self.schema)
        self.addCleanup(self.drop_schema)
        self.store=Store(self.base+('&' if '?' in self.base else '?')+'options=-csearch_path%3D'+self.schema); self.prepare()

    def drop_schema(self):
        import psycopg
        with psycopg.connect(self.base,autocommit=True) as db: db.execute('DROP SCHEMA '+self.schema+' CASCADE')


class StudioTransportTests(unittest.TestCase):
    def response(self,**extra):
        value={'operations':[{'page_index':0,'element_id':'image','changes':{'scale':1.2}},{'page_index':0,'element_id':'title','changes':{'dy':-20}}],'observation':'标题与产品图','reason':'两项调整','unsupported':False}
        return {'model':studio_vision.MODEL,'done':True,'done_reason':'stop','prompt_eval_count':200,'eval_count':50,'message':{'content':json.dumps(value)},**extra}

    def call(self,response):
        from tests.test_local_vision import Response
        with patch('backend.studio_vision.urllib.request.build_opener') as build:
            build.return_value.open.return_value=Response(json.dumps(response).encode())
            result=studio_vision.complete({'feedback':'放大图片并上移标题'},[PNG.split(',')[1]])
        return result,build

    def test_real_image_sent_with_strict_schema_no_proxy_or_tool(self):
        result,build=self.call(self.response())
        self.assertEqual(len(result['operations']),2)
        request=build.return_value.open.call_args.args[0]; payload=json.loads(request.data)
        self.assertEqual(payload['messages'][1]['images'],[PNG.split(',')[1]])
        self.assertEqual(payload['format'],studio_vision.SCHEMA)
        self.assertEqual(build.call_args.args[0].proxies,{})
        self.assertNotIn('tools',payload); self.assertEqual(build.return_value.open.call_count,1)

    def test_current_values_are_explicit_cumulative_and_override_visual_defaults(self):
        state={'assets':[],'current':{'template':'xhs-a','options':{'studio':{'pages':{'0':{'image':{'scale':.9,'dx':12},'background':{'color':'#e7f0e7'}}}}}},'messages':[{'role':'assistant','text':'上轮修改','operations':[{'page_index':0,'element_id':'image','changes':{'scale':.9}}]}]}
        context,_,_=studio_vision.prepare(fake_preview(None),state,'产品图再小一点，保持背景',0,'image',None)
        self.assertEqual(context['selected']['current_values']['scale'],.9)
        self.assertEqual(context['selected']['current_values']['dx'],12)
        self.assertEqual(context['selected']['current_values']['dy'],0)
        self.assertEqual(context['current_page_parameters']['background']['color'],'#e7f0e7')
        self.assertEqual(context['pages'][0]['current_parameters']['image']['scale'],.9)
        self.assertEqual(context['recent_executed_operations'][0][0]['changes']['scale'],.9)
        self.assertIn('scale=0.9',studio_vision.SYSTEM)

    def test_latest_user_request_is_last_and_old_visual_claim_is_not_replayed(self):
        from tests.test_local_vision import Response
        context={'feedback':'再小一点，保持背景','selected':{'current_values':{'scale':.9}},'recent_messages':[{'role':'user','text':'改背景并缩小到.9'},{'role':'assistant','operations':[{'page_index':0,'element_id':'image','changes':{'scale':.9}}],'text':'错误推断当前scale为1.0'}]}
        with patch('backend.studio_vision.urllib.request.build_opener') as build:
            build.return_value.open.return_value=Response(json.dumps(self.response()).encode())
            studio_vision.complete(context,[PNG.split(',')[1]])
        payload=json.loads(build.return_value.open.call_args.args[0].data)
        self.assertEqual([m['role'] for m in payload['messages']],['system','user','assistant','user'])
        self.assertIn('本轮唯一新要求：再小一点，保持背景',payload['messages'][-1]['content'])
        self.assertNotIn('错误推断',json.dumps(payload,ensure_ascii=False))
        self.assertIn('previous_committed_operations',payload['messages'][-2]['content'])
        self.assertEqual(payload['messages'][-1]['images'],[PNG.split(',')[1]])

    def test_output_schema_discriminates_elements_and_available_product_ids(self):
        empty=studio_vision.schema_for({'assets':[{'id':'ref1','role':'reference'}],'pages':[{},{}]})
        variants=empty['properties']['operations']['items']['oneOf']
        image=next(v for v in variants if v['properties'].get('element_id',{}).get('enum')==['image'])
        self.assertNotIn('asset_id',image['properties']['changes']['properties'])
        self.assertEqual(image['properties']['changes']['properties']['placement']['enum'],['background','inline'])
        text=next(v for v in variants if v['properties'].get('element_id',{}).get('enum')==['title','body'])
        self.assertEqual(text['properties']['changes']['properties']['opacity'],{'type':'number','minimum':0,'maximum':1})
        background=next(v for v in variants if v['properties'].get('element_id',{}).get('enum')==['background'])
        self.assertEqual(set(background['properties']['changes']['properties']),{'color'})
        self.assertEqual(image['properties']['page_index']['maximum'],1)
        populated=studio_vision.schema_for({'assets':[{'id':'product1','role':'product'},{'id':'ref1','role':'reference'}]})
        image=next(v for v in populated['properties']['operations']['items']['oneOf'] if v['properties'].get('element_id',{}).get('enum')==['image'])
        self.assertEqual(image['properties']['changes']['properties']['asset_id']['enum'],['product1'])

    def test_unknown_usage_truncation_and_invalid_json_never_applied(self):
        cases=[self.response(prompt_eval_count=None),self.response(done_reason='length'),self.response(message={'content':'```json {} ```'}),self.response(model='other')]
        for case in cases:
            with self.subTest(case=case),self.assertRaises(DomainError): self.call(case)

    def test_selected_reference_only_and_invalid_region_rejected(self):
        state={'assets':[{'id':'a','name':'A','role':'reference','data_url':PNG},{'id':'b','name':'B','role':'reference','data_url':PNG}],'current':{'template':'xhs-e','options':{}},'messages':[]}
        context,images,sources=studio_vision.prepare(fake_preview(None),state,'参考A',0,None,None,'a')
        self.assertEqual([s['id'] for s in sources],['0','a']); self.assertEqual(len(images),2)
        _,images,sources=studio_vision.prepare(fake_preview(None),state,'不附参考',0,None,None)
        self.assertEqual([s['role'] for s in sources],['canvas']); self.assertEqual(len(images),1)
        for region in ({'x':0,'y':0,'width':0,'height':1},{'x':0,'y':0,'width':1200,'height':10}):
            with self.assertRaises(DomainError): studio_vision.prepare(fake_preview(None),state,'移动',0,None,region)
