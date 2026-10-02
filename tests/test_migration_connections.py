"""Migration owns and closes its real SQLite snapshot reader, without relying on GC."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from backend import migrate
from backend.contracts import DomainError
from backend.operations import Operations
from backend.store import Store


class TrackedConnection(sqlite3.Connection):
    close_calls = 0
    fail_query = None

    def execute(self, sql, parameters=()):
        if sql == self.fail_query:
            raise sqlite3.OperationalError('injected snapshot read failure')
        return super().execute(sql, parameters)

    def close(self):
        self.close_calls += 1
        super().close()


class MigrationConnectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.source = Path(self.tmp.name) / 'source.sqlite'
        self.target = Path(self.tmp.name) / 'target.sqlite'
        source_store = Store(self.source)
        operations = Operations(source_store)
        self.run = source_store.create('legacy-owner', 'snapshot', {'topic': '整理已有衣物'})
        operations.command('legacy-owner', {'action': 'load_sample', 'payload': {}, 'version': 0, 'key': 'sample'})
        self.original_source = self.source.read_bytes()

    @contextmanager
    def tracked_readers(self, fail_query=None):
        readers = []
        def connect(*args, **kwargs):
            connection = sqlite3.connect(*args, **kwargs, factory=TrackedConnection)
            connection.fail_query = fail_query
            readers.append(connection)
            return connection
        # Replace only migrate's module reference, not every Store's connection.
        with patch.object(migrate, 'sqlite3', SimpleNamespace(connect=connect)):
            try:
                yield readers
            finally:
                # On a regression, retain deterministic fixture cleanup after the
                # assertion fails; this does not make an unclosed reader pass.
                for reader in readers:
                    if not reader.close_calls:
                        reader.close()

    def assert_closed(self, readers, expected_count):
        self.assertEqual(len(readers), expected_count)
        for reader in readers:
            self.assertEqual(reader.close_calls, 1)
            with self.assertRaisesRegex(sqlite3.ProgrammingError, 'closed'):
                reader.execute('SELECT 1')
        self.assertEqual(self.source.read_bytes(), self.original_source)

    def test_success_closes_reader_and_preserves_source_and_copied_rows(self):
        with self.tracked_readers() as readers:
            report = migrate.copy_database(self.source, self.target)
            self.assertTrue(report['verified'])
            self.assertEqual(report['counts']['runs'], 1)
            copied = Store(self.target).get(self.run.run_id, 'legacy-owner')
            self.assertEqual(copied, self.run)
            self.assert_closed(readers, 1)

    def test_identical_replay_closes_each_reader_without_garbage_collection(self):
        with self.tracked_readers() as readers:
            report = migrate.copy_database(self.source, self.target)
            self.assertEqual(migrate.copy_database(self.source, self.target), report)
            self.assert_closed(readers, 2)
            with Store(self.target).connect() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM runs').fetchone()[0], 1)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM import_batches').fetchone()[0], 1)

    def test_snapshot_read_failure_closes_reader_and_imports_no_business_rows(self):
        query = 'SELECT id,owner,payload FROM runs ORDER BY rowid'
        with self.tracked_readers(fail_query=query) as readers:
            with self.assertRaisesRegex(sqlite3.OperationalError, 'snapshot read failure'):
                migrate.copy_database(self.source, self.target)
            self.assert_closed(readers, 1)
            with Store(self.target).connect() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM runs').fetchone()[0], 0)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM import_batches').fetchone()[0], 0)

    def test_snapshot_begin_failure_still_closes_its_reader(self):
        with self.tracked_readers(fail_query='BEGIN') as readers:
            with self.assertRaisesRegex(sqlite3.OperationalError, 'snapshot read failure'):
                migrate.copy_database(self.source, self.target)
            self.assert_closed(readers, 1)

    def test_changed_target_rejection_closes_reader_and_does_not_overwrite(self):
        with self.tracked_readers() as readers:
            report = migrate.copy_database(self.source, self.target)
            self.assertEqual(migrate.copy_database(self.source, self.target), report)
            with Store(self.target).connect() as db:
                db.execute("UPDATE runs SET payload='{}'")
            with self.assertRaises(DomainError) as error:
                migrate.copy_database(self.source, self.target)
            self.assertEqual(error.exception.code, 'MIGRATION_CONFLICT')
            self.assert_closed(readers, 3)
            with Store(self.target).connect() as db:
                self.assertEqual(db.execute('SELECT payload FROM runs').fetchall(), [('{}',)])
                self.assertEqual(db.execute('SELECT COUNT(*) FROM import_batches').fetchone()[0], 1)


if __name__ == '__main__':
    unittest.main()
