"""Optional local public-search connector. Never downloads or logs credentials."""
import json
import os
from pathlib import Path
import socket
import subprocess
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def healthy():
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open('http://127.0.0.1:18060/health', timeout=2) as response:
            data = json.loads(response.read(8192))
            return response.status == 200 and isinstance(data, dict) and data.get('success') is True
    except (OSError, ValueError):
        return False


def start_optional(root=ROOT):
    """Return only an owned child; existing/unconfigured services return None."""
    folder = Path(root).resolve() / 'runtime' / 'xhs'
    binary = folder / ('xiaohongshu-mcp.exe' if os.name == 'nt' else 'xiaohongshu-mcp')
    try:
        token = (folder / 'auth-token').read_text(encoding='utf-8').strip()
    except OSError:
        return None
    if not token or not binary.is_file():
        return None
    if healthy():
        print('Public search: using existing local connector.', flush=True)
        return None
    with socket.socket() as probe:
        try:
            probe.bind(('127.0.0.1', 18060))
        except OSError:
            print('Public search: port occupied; existing service left untouched.', flush=True)
            return None
    env = {**os.environ, 'AUTH_TOKEN': token, 'COOKIES_PATH': str(folder / 'cookies.json')}
    try:
        # Token goes through the environment, never command arguments or logs.
        # Suppress upstream logs, which may contain authentication details.
        child = subprocess.Popen([str(binary), '-port', '127.0.0.1:18060', '-headless=true'],
                                 cwd=folder, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        print('Public search: connector unavailable; website can continue.', flush=True)
        return None
    print('Public search: local connector starting on 127.0.0.1:18060.', flush=True)
    return child


def main():
    child = start_optional()
    if child is None:
        print('No connector started. Configure runtime/xhs binary and auth-token, or reuse the existing service.')
        return 0
    try:
        return child.wait()
    except KeyboardInterrupt:
        child.terminate()
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=5)
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
