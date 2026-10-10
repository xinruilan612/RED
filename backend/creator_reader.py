"""Fixed local creator-page reader; authentication never leaves the local profile."""
import json
import os
import re
import signal
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _process_snapshot():
    # Never inspect argv or environment: either may contain session material.
    result=subprocess.run(['/bin/ps','-axo','pid=,ppid=,pgid=,stat=,lstart='],
                          capture_output=True,text=True,timeout=3,check=True)
    rows={}
    for line in result.stdout.splitlines():
        parts=line.split(None,4)
        if len(parts)==5 and not parts[3].startswith('Z'):
            pid,parent,group=map(int,parts[:3])
            rows[pid]=(parent,group,parts[4])
    return rows


def _reader_family(root, snapshot):
    found={root}
    while True:
        additions={pid for pid,(parent,_,_) in snapshot.items() if parent in found}
        if additions<=found:break
        found.update(additions)
    return {pid:snapshot[pid] for pid in found if pid in snapshot}


def _signal_family(family, sig):
    current=_process_snapshot()
    alive={pid:row for pid,row in family.items() if pid in current
           and current[pid][1:]==row[1:]}
    # Only groups whose leader was a verified reader descendant are owned.
    # A descendant in an unrelated shared group is signalled individually.
    groups={row[1] for row in alive.values() if row[1] in family}
    if sig==0:return bool(alive)
    for group in groups:
        try:os.killpg(group,sig)
        except ProcessLookupError:pass
    for pid,row in alive.items():
        if row[1] not in groups:
            try:os.kill(pid,sig)
            except ProcessLookupError:pass
    return bool(alive)


def run_reader(command, **kwargs):
    process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, start_new_session=True)
    try:
        stdout, stderr = process.communicate(timeout=kwargs.get('timeout',240))
    except subprocess.TimeoutExpired:
        # Chromium has its own process group. Discover the reader's descendants
        # before killing its parent, then retain their process start signatures
        # across reparenting. Never match browser names or another user's profile.
        try:
            family=_reader_family(process.pid,_process_snapshot())
            detached={pid:row for pid,row in family.items() if row[1]!=process.pid}
            _signal_family(detached,signal.SIGTERM)
            deadline=time.monotonic()+5
            while time.monotonic()<deadline:
                if not _signal_family(detached,0):break
                time.sleep(.05)
            _signal_family(detached,signal.SIGKILL)
            # Keep the driver/reader alive until independent browser groups are
            # stopped, avoiding orphaned browsers and allowing normal reaping.
            _signal_family({pid:row for pid,row in family.items() if row[1]==process.pid},signal.SIGTERM)
            try:process.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                _signal_family(family,signal.SIGKILL)
        except (OSError,ValueError,subprocess.SubprocessError):
            # If process inventory is unavailable, only our directly owned
            # process group may be killed; never widen the target by executable.
            try:os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:pass
        finally:
            try:process.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.stdout.close();process.stderr.close()
                process.wait(timeout=3)
        raise
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def collect_creator(source_id, runner=run_reader):
    base = {'status': 'unavailable', 'source_id': source_id, 'account': None, 'notes': [],
            'source_method': 'creator_browser_dom', 'source_updated_at': None,
            'error': 'CREATOR_NOT_BOUND'}
    if not isinstance(source_id, str) or not re.fullmatch(r'[0-9a-f]{24}', source_id):
        return {**base, 'error': 'CREATOR_IDENTITY_INVALID'}
    binding = ROOT / 'runtime/xhs-local/creator' / source_id / 'binding.json'
    if not binding.is_file():
        return base
    executable = ROOT / 'runtime/mediacrawler/.venv/bin/python'
    if not executable.is_file():
        return {**base, 'error': 'CREATOR_RUNTIME_UNAVAILABLE'}
    try:
        result = runner([str(executable), str(ROOT / 'scripts/xhs_creator_reader.py'),
                         '--source-id', source_id], cwd=ROOT, capture_output=True,
                        timeout=240, check=False)
        if result.returncode != 0 or len(result.stdout) > 1_000_000:
            raise ValueError('invalid subprocess result')
        value = json.loads(result.stdout)
        if not isinstance(value, dict) or value.get('source_id') != source_id:
            raise ValueError('invalid identity')
        if value.get('status') not in ('synced', 'partial', 'failed', 'unavailable'):
            raise ValueError('invalid status')
        return value
    except (OSError, ValueError, subprocess.SubprocessError):
        return {**base, 'status': 'failed', 'error': 'CREATOR_READER_FAILED'}
