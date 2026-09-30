import json
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from backend.accounts import PROFILE_FIELDS
from backend.contracts import DomainError
from backend.execution import Executor
from backend.operations import Operations
from backend.operations_planner import OperationsPlanner, build_snapshot, validate_plan
from backend.provider import Config
from backend.store import Store


class PlanningFixture:
    def __init__(self):
        self.calls=0

    def complete_result(self,messages):
        self.calls+=1
        data=json.loads(messages[1]['content'])
        pillars=data['allowed_pillars']
        refs=['profile:goal','profile:audience']
        tasks=[]
        examples=[('新人常见误区','图文清单','先检查一个容易忽略的构图问题'),
                  ('同一地点两种光线','前后对比','用一组照片展示光线变化'),
                  ('拍摄现场怎么选角度','幕后记录','说明现场如何取舍机位')]
        for i in range(3):
            title,fmt,action=examples[i]
            tasks.append({'day_offset':i*2,'pillar':pillars[i%len(pillars)],'title':title,
                'format':fmt,'angle':action,'action':action,'reason':'依据当前账号目标安排；目前没有历史表现数据，本条由档案假设形成。',
                'success_signal':'记录目标受众是否收藏或提出具体问题','basis_refs':refs})
        return {'weekly_summary':'围绕目标受众安排三种不同表达，并在发布后记录真实反应。',
                'data_gaps':['没有可用于判断账号历史表现的作品指标'],'tasks':tasks},24,{'request_id':'fixture-plan'}


class OperationsPlannerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(Path(self.tmp.name)/'planner.sqlite')
        self.ops=Operations(self.store);self.owner='creator';self.client=PlanningFixture()
        self.config=Config(api_key='test-only')
        self.executor=Executor(self.store,self.config,self.client)
        self.planner=OperationsPlanner(self.store,self.ops,self.executor)
        profile={k:'' for k in PROFILE_FIELDS}
        profile.update(positioning='人像摄影博主',audience='刚入门的大学生摄影爱好者',
            pillars='拍摄技巧, 修图前后对比, 拍摄幕后',goal='吸引摄影兴趣用户关注',
            resources='每周 2–4 小时, 主要用手机拍摄, 已有可用照片或视频素材',weekly_frequency=3)
        state=self.ops.command(self.owner,{'action':'save_account','payload':{'id':'','name':'摄影号','platform':'xiaohongshu','profile':profile},'version':self.ops.read(self.owner)['version'],'key':str(uuid4())})
        self.account=state['accounts'][-1]

    def tearDown(self):self.tmp.cleanup()

    def request(self,key=None):
        return {'account_id':self.account['id'],'week_start':'2026-10-05','source_type':'manual',
                'version':self.ops.read(self.owner)['version'],'key':key or str(uuid4())}

    def test_generates_personalized_varied_tasks_once_and_replays_idempotently(self):
        request=self.request(str(uuid4()))
        result=self.planner.generate(self.owner,request)
        self.assertEqual(self.client.calls,1)
        self.assertEqual(result['plan']['execution']['model_calls'],1)
        self.assertEqual(result['plan']['execution']['stage'],'operations_plan')
        self.assertEqual(len({t['title'] for t in result['plan']['tasks']}),3)
        self.assertEqual(len({t['angle'] for t in result['plan']['tasks']}),3)
        self.assertTrue(result['plan']['data_gaps'])
        self.assertEqual(self.planner.generate(self.owner,request),result)
        self.assertEqual(self.client.calls,1)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM live_calls WHERE stage='operations_plan'").fetchone()[0],1)
            self.assertEqual(db.execute("SELECT outcome FROM model_audit WHERE stage='operations_plan'").fetchone()[0],'validated')

    def test_snapshot_uses_only_selected_account_and_keeps_missing_metrics_missing(self):
        state=self.ops.read(self.owner)
        snapshot=build_snapshot(state,self.account['id'],'manual')
        self.assertEqual(snapshot['account_id'],self.account['id'])
        self.assertEqual(snapshot['metrics'],[])
        self.assertTrue(any('没有可用于判断表现' in x for x in snapshot['data_gaps']))

    def test_rejects_fabricated_evidence_refs_and_repeated_angles(self):
        snapshot=build_snapshot(self.ops.read(self.owner),self.account['id'],'manual')
        result={'weekly_summary':'这是一个按目标安排的计划。','data_gaps':[], 'tasks':[]}
        for i in range(3):
            result['tasks'].append({'day_offset':i,'pillar':'拍摄技巧','title':f'标题{i}','format':'图文','angle':'一样的角度',
                'action':'解释方法','reason':'原因','success_signal':'观察收藏','basis_refs':['profile:goal']})
        with self.assertRaises(DomainError):validate_plan(result,snapshot)
        result['tasks'][0]['angle']='独特角度'
        result['tasks'][1]['angle']='另一个角度'
        result['tasks'][2]['angle']='第三个角度'
        result['tasks'][0]['basis_refs']=['post:invented']
        with self.assertRaises(DomainError):validate_plan(result,snapshot)

    def test_stale_account_version_does_not_call_model(self):
        request=self.request();request['version']-=1
        with self.assertRaises(DomainError):self.planner.generate(self.owner,request)
        self.assertEqual(self.client.calls,0)

    def test_agent_plan_cannot_be_forged_through_generic_operations_command(self):
        command={'action':'create_agent_plan','payload':{},'version':self.ops.read(self.owner)['version'],'key':str(uuid4())}
        with self.assertRaises(DomainError):self.ops.command(self.owner,command)

    def test_new_account_history_invalidates_agent_plan_basis(self):
        result=self.planner.generate(self.owner,self.request())
        self.assertEqual(result['plan']['status'],'draft')
        state=self.ops.read(self.owner)
        updated=self.ops.command(self.owner,{'action':'import_post','payload':{
            'account_id':self.account['id'],'title':'我新发布的人像作品','body':'用户自己导入的作品记录',
            'url':'https://www.xiaohongshu.com/explore/new-photo','published_at':'2026-09-28T12:00:00+00:00',
            'format':'image_text','pillar':'拍摄技巧','traffic':'organic'},
            'version':state['version'],'key':str(uuid4())})
        self.assertEqual(updated['plans'][0]['status'],'needs_review')

    def test_missing_model_key_is_rejected_before_any_attempt_or_call(self):
        executor=Executor(self.store,Config(),None)
        planner=OperationsPlanner(self.store,self.ops,executor)
        with self.assertRaises(DomainError) as caught:planner.generate(self.owner,self.request())
        self.assertEqual(caught.exception.code,'KEY_REQUIRED')
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM operations_plan_attempts').fetchone()[0],0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM live_calls WHERE stage='operations_plan'").fetchone()[0],0)


if __name__=='__main__':unittest.main()
