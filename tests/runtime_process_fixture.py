"""Test-only subprocess worker; not imported by the website or production worker."""
import os
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
            Path(os.environ['FIXTURE_MARKER']).write_text('ready', encoding='utf-8')
            threading.Event().wait(30)
    Worker(service,lease=float(os.environ.get('FIXTURE_LEASE', '1')),fault=fault).once()


if __name__=='__main__':main()
