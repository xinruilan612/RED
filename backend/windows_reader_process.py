"""Contain only this reader and its descendants in a Windows kill-on-close job."""
import ctypes as c
from ctypes import wintypes as w
import subprocess
import sys


class BasicLimits(c.Structure):
    _fields_ = [('process_time', c.c_longlong), ('job_time', c.c_longlong),
                ('flags', w.DWORD), ('minimum_working_set', c.c_size_t),
                ('maximum_working_set', c.c_size_t), ('active_processes', w.DWORD),
                ('affinity', c.c_size_t), ('priority', w.DWORD), ('scheduling', w.DWORD)]


class IoCounters(c.Structure):
    _fields_ = [(name, c.c_ulonglong) for name in ('read_ops', 'write_ops', 'other_ops',
                                                  'read_bytes', 'write_bytes', 'other_bytes')]


class ExtendedLimits(c.Structure):
    _fields_ = [('basic', BasicLimits), ('io', IoCounters), ('process_memory', c.c_size_t),
                ('job_memory', c.c_size_t), ('peak_process_memory', c.c_size_t),
                ('peak_job_memory', c.c_size_t)]


kernel = c.WinDLL('kernel32', use_last_error=True)


def _bind(name, result, *arguments):
    function = getattr(kernel, name)
    function.restype, function.argtypes = result, arguments
    return function


_create_job = _bind('CreateJobObjectW', w.HANDLE, c.c_void_p, w.LPCWSTR)
_set_job = _bind('SetInformationJobObject', w.BOOL, w.HANDLE, c.c_int, c.c_void_p, w.DWORD)
_assign_job = _bind('AssignProcessToJobObject', w.BOOL, w.HANDLE, w.HANDLE)
_close = _bind('CloseHandle', w.BOOL, w.HANDLE)

# Child creation cannot race job assignment: the wrapper blocks on an anonymous
# stdin pipe until its parent has put it in the job. The real reader receives no
# stdin and all its descendants inherit membership, including detached browsers.
GATED_READER = '''
import subprocess, sys
if sys.stdin.buffer.read(1) != b'1':
    sys.exit(125)
sys.exit(subprocess.call(sys.argv[1:], stdin=subprocess.DEVNULL))
'''


def run_reader(command, *, cwd, timeout):
    job = _create_job(None, None)
    if not job:
        raise c.WinError(c.get_last_error())
    process = None
    try:
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not _set_job(job, 9, c.byref(limits), c.sizeof(limits)):
            raise c.WinError(c.get_last_error())
        # Use the base interpreter (not a venv redirector which might spawn before
        # assignment); isolated/no-site mode prevents startup hooks before the gate.
        executable = getattr(sys, '_base_executable', sys.executable)
        process = subprocess.Popen([executable, '-I', '-S', '-X', 'utf8', '-B', '-c', GATED_READER, *command],
                                   cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
        # Popen's owned process handle avoids PID-reuse races; never enumerate or
        # kill by browser name, account, or a shared process group.
        if not _assign_job(job, int(process._handle)):
            raise c.WinError(c.get_last_error())
        try:
            stdout, stderr = process.communicate(input=b'1', timeout=timeout)
        except subprocess.TimeoutExpired as error:
            _close(job)
            job = None
            # Job closure terminates our entire tree, unblocking inherited pipes.
            stdout, stderr = process.communicate(timeout=5)
            raise subprocess.TimeoutExpired(command, timeout, stdout, stderr) from error
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
    finally:
        if job:
            _close(job)
        if process is not None:
            if process.poll() is None:
                process.kill()
            try:
                process.communicate(timeout=5)
            finally:
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream is not None:
                        stream.close()
