import ast
import tempfile
import unittest
from pathlib import Path
from backend.store import Store
from backend.migrations import upgrade, MIGRATIONS
from backend.schemas import Command, JobCommand, parse
from backend.contracts import DomainError


class CoreContractTests(unittest.TestCase):
    def test_path_text_io_always_declares_utf8(self):
        root = Path(__file__).resolve().parents[1]
        for folder in ('backend','scripts','tests'):
            for path in (root/folder).glob('*.py'):
                tree = ast.parse(path.read_text(encoding='utf-8'))
                for node in ast.walk(tree):
                    if not isinstance(node,ast.Call) or not isinstance(node.func,ast.Attribute): continue
                    if node.func.attr not in ('read_text','write_text'): continue
                    encodings = [keyword.value for keyword in node.keywords if keyword.arg=='encoding']
                    self.assertTrue(encodings,f'{path.relative_to(root)}:{node.lineno} 缺少显式 UTF-8 编码')
                    self.assertIsInstance(encodings[0],ast.Constant)
                    self.assertIn(encodings[0].value,('utf-8','utf-8-sig'))

    def test_sqlite_store_creates_missing_parent_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'runtime'/'nested'/'web.sqlite'
            store = Store(path)
            self.assertTrue(path.is_file())
            self.assertEqual(store.list_runs('owner'), [])

    def test_migration_reentry_and_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp)/'db')
            run = store.create('owner', 'snapshot', {'material':'原始资料'})
            with store.connect() as db:
                original = db.execute('SELECT payload FROM runs').fetchone()[0]
            upgrade(store); upgrade(store)
            with store.connect() as db:
                self.assertEqual(db.execute('SELECT payload FROM runs').fetchone()[0], original)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM core_migrations').fetchone()[0], len(MIGRATIONS))
            with self.assertRaisesRegex(DomainError, '被修改'):
                upgrade(store, ((1, MIGRATIONS[0][1]+'\n'),)+MIGRATIONS[1:])
            self.assertEqual(store.get(run.run_id,'owner').snapshot_id, 'snapshot')

    def test_failed_migration_rolls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp)/'db')
            upgrade(store)
            with self.assertRaises(Exception):
                upgrade(store, MIGRATIONS+((max(v for v,_ in MIGRATIONS)+1,'CREATE TABLE rollback_probe(id TEXT); BAD SQL'),))
            with store.connect() as db:
                self.assertFalse(db.has_table('rollback_probe'))
                self.assertEqual(db.execute('SELECT COUNT(*) FROM core_migrations').fetchone()[0],len(MIGRATIONS))

    def test_strict_commands(self):
        valid = dict(action='next',version=0,key='one',payload={})
        self.assertEqual(parse(Command,valid),valid)
        for change in ({'version':True},{'version':'0'},{'owner':'other'},{'key':''},{'action':'publish'}):
            with self.assertRaises(DomainError): parse(Command,{**valid,**change})
        self.assertEqual(parse(JobCommand,dict(action='start',version=0,key='start'))['action'],'start')
