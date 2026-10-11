"""Small cross-platform primitive for owner-only local secret/artifact files."""
from contextlib import contextmanager
import os
from pathlib import Path
import stat
from uuid import uuid4


def is_private_file(path):
    try:
        path = Path(path)
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            return False  # Includes Windows junctions and other reparse points.
        if os.name == 'nt':
            from backend.windows_private_file import is_owner_only
            return is_owner_only(path)
        return info.st_uid == os.geteuid() and info.st_mode & 0o077 == 0
    except OSError:
        return False


@contextmanager
def private_binary_file(path):
    """Create a new file, enforce privacy before writing, and close on all exits."""
    path = Path(path)
    if os.name == 'nt':
        from backend.windows_private_file import create_private_fd
        fd = create_private_fd(path)
    else:
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as handle:
        if not is_private_file(path):
            raise PermissionError('Owner-only file permissions could not be verified')
        yield handle


def write_private_bytes(path, data, *, replace=False):
    """Atomically publish a protected file, without clobbering unless requested."""
    path = Path(path)
    temporary = path.with_name('.' + path.name + '-' + uuid4().hex + '.tmp')
    try:
        with private_binary_file(temporary) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if replace:
            os.replace(temporary, path)
        else:
            os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
