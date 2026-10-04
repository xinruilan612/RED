"""Contracts for crash-test orchestration, never real model or user data."""
import contextlib
import io
import json
import unittest
from unittest.mock import MagicMock, patch

import runtime_process_fixture as fixture


class RuntimeProcessFixtureTests(unittest.TestCase):
    def setUp(self):
        self.environment={'FIXTURE_DATABASE_URL':'test-only.sqlite','FIXTURE_RUN_ID':'owned-run',
                          'FIXTURE_OWNER':'test-owner','FIXTURE_POINT':'after_response',
                          'FIXTURE_STAGE':'strategy','FIXTURE_MARKER':'test-only.marker'}
        self.service=MagicMock()
        self.service.jobs.public.return_value={'status':'waiting','error':None}
        self.worker=MagicMock()
        self.worker.once.return_value=True

    def execute(self):
        with patch.dict(fixture.os.environ,self.environment,clear=True), \
             patch.object(fixture,'Store'),patch.object(fixture,'FixtureModel'), \
             patch.object(fixture,'Service',return_value=self.service), \
             patch.object(fixture,'Worker',return_value=self.worker) as constructor, \
             contextlib.redirect_stdout(io.StringIO()) as output:
            fixture.main()
        return constructor,output.getvalue()

    def test_crash_worker_uses_production_lease_not_one_second(self):
        constructor,output=self.execute()
        self.assertEqual(constructor.call_args.args,(self.service,))
        self.assertEqual(set(constructor.call_args.kwargs),{'fault'})
        self.service.jobs.public.assert_called_once_with('owned-run','test-owner')
        self.assertEqual(json.loads(output),{'status':'waiting','error':None})

    def test_no_claim_is_an_explicit_process_failure(self):
        self.worker.once.return_value=False
        with self.assertRaisesRegex(RuntimeError,'did not claim a job'):self.execute()
        self.service.jobs.public.assert_not_called()

    def test_blocked_worker_reports_the_persisted_failure(self):
        self.service.jobs.public.return_value={'status':'blocked','error':'Worker 租约已失效'}
        with self.assertRaisesRegex(RuntimeError,'fixture worker blocked: Worker 租约已失效'):
            self.execute()

    def test_fault_marks_only_the_requested_boundary_in_utf8(self):
        constructor,_=self.execute()
        fault=constructor.call_args.kwargs['fault']
        with patch.dict(fixture.os.environ,self.environment,clear=True), \
             patch.object(fixture,'Path') as path,patch.object(fixture.threading,'Event') as event:
            fault('after_commit','strategy')
            fault('after_response','audience')
            path.assert_not_called();event.assert_not_called()
            fault('after_response','strategy')
            path.assert_called_once_with('test-only.marker')
            path.return_value.write_text.assert_called_once_with('ready',encoding='utf-8')
            event.return_value.wait.assert_called_once_with(30)


if __name__=='__main__':unittest.main()
