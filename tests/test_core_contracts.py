import tempfile
import unittest
from pathlib import Path
from backend.store import Store
from backend.migrations import upgrade, MIGRATIONS
from backend.schemas import Command, JobCommand, parse
from backend.contracts import DomainError


class CoreContractTests(unittest.TestCase):
    def test_migration_reentry_and_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp)/'db')
            run = store.create('owner', 'snapshot', {'material':'原始资料'})
            with store.connect() as db:
                original = db.execute('SELECT payload FROM runs').fetchone()[0]
            upgrade(store); upgrade(store)
            with store.connect() as db:
                self.assertEqual(db.execute('SELECT payload FROM runs').fetchone()[0], original)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM core_migrations').fetchone()[0], 1)
            with self.assertRaisesRegex(DomainError, '被修改'):
                upgrade(store, ((1, MIGRATIONS[0][1]+'\n'),))
            self.assertEqual(store.get(run.run_id,'owner').snapshot_id, 'snapshot')

    def test_failed_migration_rolls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp)/'db')
            upgrade(store)
            with self.assertRaises(Exception):
                upgrade(store, MIGRATIONS+((2,'CREATE TABLE rollback_probe(id TEXT); BAD SQL'),))
            with store.connect() as db:
                self.assertFalse(db.has_table('rollback_probe'))
                self.assertEqual(db.execute('SELECT COUNT(*) FROM core_migrations').fetchone()[0],1)

    def test_strict_commands(self):
        valid = dict(action='next',version=0,key='one',payload={})
        self.assertEqual(parse(Command,valid),valid)
        for change in ({'version':True},{'version':'0'},{'owner':'other'},{'key':''},{'action':'publish'}):
            with self.assertRaises(DomainError): parse(Command,{**valid,**change})
        self.assertEqual(parse(JobCommand,dict(action='start',version=0,key='start'))['action'],'start')
