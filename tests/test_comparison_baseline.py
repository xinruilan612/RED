import json
import os
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4
from backend.store import Store
from backend.service import Service
from backend.provider import Config
from backend.contracts import DomainError
from backend.comparison_baseline import generate

class Adapter:
    def __init__(self):self.calls=0;self.bad=False;self.fail=False
    def complete(self,messages):
        self.calls+=1;self.messages=messages
        if self.fail:raise RuntimeError('transport')
        return ({'oops':'invalid'} if self.bad else {'title':'大学生日常鼠标怎么选','body':'根据材料检查USB接口。'}),100

class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(Path(self.tmp.name)/'site.sqlite');self.prepare()
    def prepare(self):
        self.fixture=Adapter();self.service=Service(self.store,Config('fixture',run_budget_usd=10,day_budget_usd=100),self.fixture)
        self.brief={'topic':'大学生鼠标公开资料推广','audience':'大学生','tone':'自然具体','material':'USB接收器。只能引用材料，不能编造价格。','allow_hypothesis':False,'mode':'live'}
        self.run=self.service.create('owner',self.brief)
    def tearDown(self):self.tmp.cleanup()
    def generate(self,owner='owner',ack=True):return generate(self.service,owner,self.run['run_id'],ack)
    def test_one_call_same_input_audit_and_restart_reuse(self):
        value=self.generate();again=self.generate()
        self.assertEqual(value,again);self.assertEqual(self.fixture.calls,1)
        self.assertEqual(value['input']['material'],self.brief['material'])
        self.assertEqual(json.loads(self.fixture.messages[1]['content']),value['input'])
        with self.store.connect() as db:
            row=db.execute('SELECT prompt_version,outcome,sources FROM model_audit WHERE call_id=?',(value['execution']['call_id'],)).fetchone()
        self.assertEqual(row[0],'single_call_comparison.v1');self.assertEqual(row[1],'validated');self.assertIn(value['input_hash'],row[2])
        self.assertEqual(self.store.get(self.run['run_id'],'owner').drafts,[])
    def test_known_transport_schema_metadata_is_losslessly_ignored(self):
        from backend.comparison_baseline import validate
        self.assertEqual(validate({'title':'标题','body':'正文','_schema':'json_object'}),{'title':'标题','body':'正文'})
        with self.assertRaises(DomainError):validate({'title':'标题','body':'正文','other':'extra'})

    def test_authorization_and_explicit_paid_ack(self):
        for owner,ack in [('other',True),('owner',False),('owner',1)]:
            with self.assertRaises(DomainError):self.generate(owner,ack)
        self.assertEqual(self.fixture.calls,0)
    def test_invalid_response_is_not_recharged(self):
        self.fixture.bad=True
        for _ in range(2):
            with self.assertRaises(DomainError):self.generate()
        self.assertEqual(self.fixture.calls,1)
    def test_unknown_transport_never_retries(self):
        self.fixture.fail=True
        for _ in range(2):
            with self.assertRaises(DomainError):self.generate()
        self.assertEqual(self.fixture.calls,1)
    def test_extra_sources_rejected_to_keep_same_information(self):
        from dataclasses import asdict
        r=self.store.get(self.run['run_id'],'owner');r.context['evidence']=[{'text':'additional'}]
        with self.store.connect() as db:db.execute('UPDATE runs SET payload=? WHERE id=?',(json.dumps(asdict(r)),r.run_id))
        with self.assertRaises(DomainError):self.generate()
        self.assertEqual(self.fixture.calls,0)

@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'),'requires actual PostgreSQL')
class PostgresComparisonTests(ComparisonTests):
    def setUp(self):
        from backend.database import connect
        self.tmp=tempfile.TemporaryDirectory();self.schema='comparison_'+uuid4().hex
        self.base=os.environ['TEST_DATABASE_URL']
        with connect(self.base) as db:db.execute('CREATE SCHEMA '+self.schema)
        self.store=Store(self.base+('?options=-csearch_path%3D'+self.schema if '?' not in self.base else '&options=-csearch_path%3D'+self.schema));self.prepare()
    def tearDown(self):
        from backend.database import connect
        with connect(self.base) as db:db.execute('DROP SCHEMA '+self.schema+' CASCADE')
        self.tmp.cleanup()
