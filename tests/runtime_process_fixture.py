"""Test-only subprocess worker; not imported by the website or production worker."""
import os
import json
import threading
from pathlib import Path
from backend.store import Store
from backend.service import Service
from backend.provider import Config
from backend.worker import Worker
from test_live_provider import FixtureModel


def main():
    service=Service(Store(os.environ['FIXTURE_DATABASE_URL']),Config('fixture-key'),FixtureModel())
    def fault(point,stage):
        if point==os.environ.get('FIXTURE_POINT') and stage==os.environ.get('FIXTURE_STAGE'):
            Path(os.environ['FIXTURE_MARKER']).write_text('ready',encoding='utf-8')
            threading.Event().wait(30)
    # A one-second lease measured filesystem speed rather than crash recovery.
    # Keep the actual production lease; the parent expires only the killed job.
    if not Worker(service,fault=fault).once():
        raise RuntimeError('fixture worker did not claim a job')
    job=service.jobs.public(os.environ['FIXTURE_RUN_ID'],os.environ['FIXTURE_OWNER'])
    print(json.dumps(job,ensure_ascii=False),flush=True)
    if job['status']=='blocked':
        raise RuntimeError('fixture worker blocked: '+str(job['error']))


if __name__=='__main__':main()
