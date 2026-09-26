"""Subprocess crash fixture: never imports a real provider adapter to make calls."""
import os
import time
from pathlib import Path
from backend.store import Store
from backend.service import Service
from backend.provider import Config
from backend.worker import Worker
from test_windtunnel_runtime import Fixture

store=Store(os.environ['FIXTURE_DATABASE_URL'])
fixture=Fixture(store,os.environ['FIXTURE_OWNER'])
service=Service(store,Config('fixture-only',run_budget_usd=10,day_budget_usd=100),fixture)
def fault(point,stage):
    if point==os.environ['FIXTURE_POINT'] and stage=='wt_read':
        Path(os.environ['FIXTURE_MARKER']).write_text('reached crash point')
        while True:time.sleep(.1)
Worker(service,lease=1,fault=fault).once()
