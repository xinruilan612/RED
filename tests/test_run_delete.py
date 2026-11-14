"""Permanent run deletion: terminal only, owner scoped, list disappears."""
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from backend.contracts import DomainError
from backend.provider import Config
from backend.service import Service
from backend.store import Store


class RunDeleteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'test.sqlite')
        self.service = Service(self.store, Config())
        self.owner = 'alice'
        self.run = self.service.create(self.owner, dict(topic='待删除', audience='读者', tone='真实', material='素材', scenario='standard'))

    def cancel(self):
        self.run = self.service.action(self.owner, self.run['run_id'], dict(
            action='cancel', version=self.run['status_version'], key=str(uuid4()), payload={}))

    def test_active_run_must_be_cancelled_before_delete(self):
        with self.assertRaises(DomainError):
            self.service.delete_run(self.owner, self.run['run_id'])
        self.cancel()
        self.assertTrue(self.service.delete_run(self.owner, self.run['run_id'])['deleted'])
        with self.assertRaises(DomainError):
            self.store.get(self.run['run_id'], self.owner)
        self.assertEqual([r for r in self.store.list_runs(self.owner) if r.run_id == self.run['run_id']], [])

    def test_other_owner_cannot_delete(self):
        self.cancel()
        with self.assertRaises(DomainError):
            self.service.delete_run('bob', self.run['run_id'])
        self.assertEqual(self.store.get(self.run['run_id'], self.owner).run_id, self.run['run_id'])
