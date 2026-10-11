"""Build a Windows x64 teacher portable ZIP, without local accounts or state.

Run with an already verified official Python 3.12 embeddable ZIP and a matching
Windows CPython 3.12 site-packages directory. No downloads or pip execution.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import zipfile


ROOT = Path(__file__).resolve().parents[1]
DENIED_DIRS = {'.git', '.venv', 'venv', 'runtime', 'data', 'node_modules',
               '__pycache__', '.cache', '.pytest_cache', '.mypy_cache', '.ruff_cache',
               'output', 'outputs', 'dist', 'build', 'db', 'cache', 'browser_state', 'browserstate',
               'browser-profile', 'browser_profile', 'user_data', '.aws', '.ssh'}
DENIED_SUFFIXES = {'.db', '.sqlite', '.sqlite3', '.pyc', '.pyo', '.zip', '.7z',
                   '.tar', '.gz', '.pem', '.key', '.p12', '.pfx', '.kdbx'}
BUILD_TOOLS = {'pip', 'setuptools', 'wheel', 'build', 'uv', '_distutils_hack',
               'pkg_resources', 'distutils-precedence.pth'}
TEXT_SUFFIXES = {'.py', '.js', '.cjs', '.md', '.txt', '.json', '.yaml', '.yml',
                 '.html', '.css', '.csv', '.svg', '.cmd', '.ps1', '.sh', '.log',
                 '.snapshot', '.patch', '.example', '.service', '.pth', '._pth', '.pem'}
# Reviewed no-network regression fixtures from the source baseline. Bind the
# exception to the exact file AND full line hash, not a blanket tests/ exclusion.
REVIEWED_FIXTURE_LINES = {
    'app/tests/test_connected_api.py': {'6002d6ae01dad6be23251524b452caa01ad6e20d0ff15c537d864d7ab329bfa2'},
    'app/tests/test_deploy_check.py': {'048c559ff3fc61f85b386ea379beb0421c7fb8affc51a1c5d3f3551e79ce2f36', '55f62d455f80eb67edc5939ecf661a1e1051bb8c8302f945d0c66d58e5f6f876'},
    'app/tests/test_knowledge_sources.py': {'3e026152d43940ed5b8c9532aa5d48e5070706aa8c7daf260c94f07569065cab'},
    'app/tests/test_local_dev.py': {'d19198053e94efe97e85e8365d7db31e6df9a40cfd71a0f78664ef8043f23435', '595fdc75cab267248ab83d5ef083f91b9a8735bf9b699548fccf238ef8baee50'},
    'app/tests/test_model_connections.py': {'af39c95a7d8237839cf37793a2abc7af96c8ee3fc9064c6f89fb247164756202'},
    'app/tests/test_search_providers.py': {'c53a240862e164ac203679335a1805417bda4729f56a105e2e7c52082fe8c12e'},
    'app/tests/test_document_input.py': {'da9746be193561a670218bf539461d0cdd2d9497a66875ea4ce9d17ec6b33c37'},
    'app/tests/test_production_api.py': {'694af2d3962a7d8d379bb0a1589d29e286390819e4d76305535f9c9e6ef31625'},
}
# These exact dependency bytes contain reviewed documentation URLs, environment
# variable names, OID labels and serialization delimiters, not real credentials.
# A dependency update invalidates the exception and triggers fresh review.
REVIEWED_LIBRARY_SOURCES = {
    "python/Lib/site-packages/cryptography/hazmat/_oid.py": "a7c4e18f0241e7a0a2feb008ae3c89d5ff158e00fa7b7f5eb36761f0921404ec",
    "python/Lib/site-packages/cryptography/hazmat/primitives/serialization/ssh.py": "1d5e99a888ea34d68d50be8ce2043234926d67be44b22499b3acb175da81ad62",
    "python/Lib/site-packages/httpx/_urls.py": "757f7d551d4348e1e9828f40abb3f360ee0529dc6a2a3c32369f20adff1d1cdd",
    "python/Lib/site-packages/httpx2/_urls.py": "d9fc06bca6d76d9e099738c51de8b6af245b5c6c2e6c5e386c3e8d46d4001756",
    "python/Lib/site-packages/langgraph/checkpoint/postgres/__init__.py": "fb141317b3b865da672b946df0f2e64d33da23a640dd334815604cc06b36fe1f",
    "python/Lib/site-packages/langgraph/checkpoint/postgres/shallow.py": "b8a53977483f8591a2c11cb0e1244b2455985558fb3d3aec2a4dcc4ae6e7fb44",
    "python/Lib/site-packages/langgraph/store/postgres/aio.py": "a0362f730898e615f6101537c6be0fefc6dcea2a45883ac9717a89e5daf8e57c",
    "python/Lib/site-packages/langgraph/store/postgres/base.py": "b9722a5c119f126528b50550250b8497a25a17b63b934be242ad18a4741e1878",
    "python/Lib/site-packages/langgraph_checkpoint_postgres-3.1.2.dist-info/METADATA": "bcaef7698d95c88beb8b83f3e056643e0daf96c919ec54abfe519d12dacd269d",
    "python/Lib/site-packages/langsmith/anonymizer.py": "ac3d5fe2f6d18c64c104f0e806063c0c5f8affd83c5a22dbd8077234596d6a89",
    "python/Lib/site-packages/langsmith/client.py": "d2097ff5e9b028b4705c3dba203f78febbb2b97dcf52b3c9d3f366bc6f1492e1",
    "python/Lib/site-packages/langsmith/secret.py": "17c3ac9cc88885cf2a89c22964afe0ef2da4b4bac23763fdf42092fa2371538e",
    "python/Lib/site-packages/pydantic/networks.py": "80207dea0b741bbb625438559c97e92abd4044be6a907f923d992e364986d8ee",
    "python/Lib/site-packages/urllib3/contrib/socks.py": "81141f708d6928e021e62238fd30c090a6803f737f1f620de49e660652990691",
    "python/Lib/site-packages/urllib3/util/url.py": "6a2814d91987dd9728278d413a154ee5277b15cb262d9945425377f2a693311f",
}
SECRET_PATTERNS = {
    'provider_key': re.compile(r'\bsk-(?:proj-|ant-api\d+-)?[A-Za-z0-9_-]{20,}'),
    'github_token': re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,})'),
    'aws_access_key': re.compile(r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b'),
    'slack_token': re.compile(r'\bxox[baprs]-[A-Za-z0-9-]{20,}'),
    'private_key': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'credential_url': re.compile(r'\b[a-z][a-z0-9+.-]*://[^\s/:]+:([^\s/@]+)@', re.I),
    'literal_credential': re.compile(
        r'''(?i)(?:[A-Z_]*API_KEY|ACCESS_TOKEN|AUTH_TOKEN|SECRET_KEY|PASSWORD)["']?\s*[=:]\s*["']([^"'\r\n]{16,})["']'''),
    'environment_credential': re.compile(
        r'(?m)^[ \t]*(?:[A-Z_]*API_KEY|ACCESS_TOKEN|AUTH_TOKEN|SECRET_KEY|PASSWORD)[ \t]*=[ \t]*([A-Za-z0-9_+/=-]{16,})[ \t]*$'),
}


class PackageError(ValueError):
    """A redacted, actionable build refusal; never includes credential values."""


def _git(repo: Path, *args: str) -> bytes:
    result = subprocess.run(['git', '-C', str(repo), *args], capture_output=True)
    if result.returncode:
        raise PackageError('Git source inventory failed; verify --repo and git availability')
    return result.stdout


def _relative(name: str) -> str:
    path = PurePosixPath(name)
    if (not name or '\\' in name or ':' in name or path.is_absolute()
            or any(part in {'', '.', '..'} for part in name.split('/'))
            or any(ord(char) < 32 for char in name)):
        raise PackageError('Unsafe relative package path')
    # Windows extraction must not create alternate streams, reserved names or aliases.
    for part in path.parts:
        if part.endswith((' ', '.')) or re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', part):
            raise PackageError('Unsupported Windows package filename')
    return path.as_posix()


def _source_allowed(name: str) -> bool:
    path = PurePosixPath(_relative(name))
    lower = [part.lower() for part in path.parts]
    basename = lower[-1]
    return not (
        any(part in DENIED_DIRS for part in lower)
        or (basename.startswith('.env') and not basename.endswith('.example'))
        or basename in {'cookies.json', 'cookie.json', 'storage_state.json', 'credentials.json',
                        'tokens.json', 'secrets.json', 'id_rsa', 'id_ed25519'}
        or path.suffix.lower() in DENIED_SUFFIXES
        or basename.endswith(('-wal', '-shm', '.db-journal'))
    )


def _regular_file(root: Path, relative: str) -> Path:
    path = root
    for part in PurePosixPath(_relative(relative)).parts:
        path = path / part
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise PackageError(f'Symlink/reparse point refused: {relative}')
    if not path.resolve().is_relative_to(root.resolve()) or not path.is_file():
        raise PackageError(f'Non-regular or external source refused: {relative}')
    return path


def _root(path: Path) -> Path:
    path = path.absolute()
    for item in (path, *path.parents):
        info = item.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise PackageError('Input directory contains a symlink/reparse point')
    return path.resolve()


def secret_candidates(name: str, content: bytes) -> list[dict]:
    """Conservative preflight, not a proof of absence; candidates contain no values.

    Known test sentinels are recognised by their literal placeholder shape, never
    by excluding all tests (or all files named credentials). A separate review is
    still required for the produced package.
    """
    if REVIEWED_LIBRARY_SOURCES.get(name) == hashlib.sha256(content).hexdigest():
        return []
    text = content.decode('utf-8', errors='replace')
    findings = []
    for rule, pattern in SECRET_PATTERNS.items():
        for match in pattern.finditer(text):
            value = match.group(1) if match.lastindex else match.group(0)
            line_number = text.count('\n', 0, match.start()) + 1
            line_hash = hashlib.sha256(text.splitlines()[line_number - 1].encode('utf-8')).hexdigest()
            if line_hash in REVIEWED_FIXTURE_LINES.get(name, set()):
                continue
            if re.search(r'(?i)^(?:change[_-]?me|your[_-]|example|placeholder|dummy|fake|test[_-]|not-a-real|never-public|\[redacted)', value):
                continue
            if rule == 'credential_url' and (value.lower() in {'pass', 'password', 'p'}
                                            and name.startswith('app/tests/')):
                continue
            if rule == 'private_key' and name == 'app/tests/test_process_package.py':
                fixture = '-----BEGIN ' + r'PRIVATE KEY-----\nQUJDREVG\n-----END PRIVATE KEY-----'
                if text[match.start():].startswith(fixture):
                    continue
            findings.append({'file': name, 'line': line_number,
                             'rule': rule})
    return findings


def _site_files(root: Path):
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs.sort()
        relative_dir = Path(directory).relative_to(root)
        keep = []
        for folder in dirs:
            entry = Path(directory) / folder
            info = entry.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise PackageError('Dependency directory contains a symlink/reparse point')
            top = (relative_dir / folder).parts[0].lower()
            if (folder.lower() not in {'__pycache__', '.cache', '.git'}
                    and top not in BUILD_TOOLS
                    and not any(top.startswith(tool + '-') and top.endswith('.dist-info') for tool in BUILD_TOOLS)):
                keep.append(folder)
        dirs[:] = keep
        for filename in sorted(files):
            name = (relative_dir / filename).as_posix()
            path = _regular_file(root, name)
            if path.suffix.lower() in {'.pyc', '.pyo'} or filename in BUILD_TOOLS:
                continue
            if filename.endswith(('.pth', '.egg-link')):
                raise PackageError(f'Dependency path injection requires review: {name}')
            if filename == 'direct_url.json':
                provenance = json.loads(path.read_text(encoding='utf-8'))
                url = provenance.get('url', '')
                if not isinstance(url, str) or not url.startswith('https://') or provenance.get('dir_info', {}).get('editable'):
                    raise PackageError(f'Local/editable dependency source refused: {name}')
            if path.suffix.lower() in {'.so', '.dylib'} or re.search(r'\.cp(?!312)[0-9]+-|win32', filename):
                raise PackageError(f'Non-Windows-CPython-3.12 dependency refused: {name}')
            public_ca_bundle = (name == 'certifi/cacert.pem'
                                and b'-----BEGIN CERTIFICATE-----' in path.read_bytes()
                                and b'PRIVATE KEY' not in path.read_bytes())
            # Installed package namespaces such as langchain_core/outputs are
            # code, not repository output directories. Apply file-state rules only.
            forbidden = (path.suffix.lower() in DENIED_SUFFIXES
                         or filename.lower() in {'cookies.json', 'storage_state.json', 'credentials.json', 'tokens.json', 'secrets.json'}
                         or filename.lower().startswith('.env'))
            if forbidden and not public_ca_bundle:
                raise PackageError(f'Unexpected state/credential/archive in dependencies: {name}')
            yield name, path


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(_relative(name), date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    return info


def _textual(name: str, data: bytes) -> bool:
    if Path(name).suffix.lower() in TEXT_SUFFIXES:
        return True
    if b'\0' in data:
        return False
    try:
        data.decode('utf-8')
        return True
    except UnicodeDecodeError:
        return False


def build(output, python_embed, site_packages, repo=ROOT, include_new=(), python_embed_version=None):
    repo, site_packages = _root(Path(repo)), _root(Path(site_packages))
    embed = Path(python_embed).absolute()
    _regular_file(_root(embed.parent), embed.name)
    detected = re.fullmatch(r'python-(3\.12\.\d+)-embed-amd64\.zip', embed.name)
    version = python_embed_version or (detected.group(1) if detected else '')
    if not re.fullmatch(r'3\.12\.\d+', version) or (detected and detected.group(1) != version):
        raise PackageError('Provide the matching official Python 3.12.x x64 embeddable archive/version')
    output = Path(output).absolute()
    if output.suffix.lower() != '.zip':
        raise PackageError('--output must be a new .zip file')
    sidecar = output.with_suffix(output.suffix + '.sha256')
    external_manifest = output.with_suffix(output.suffix + '.manifest.json')
    if any(path.exists() or path.is_symlink() for path in (output, sidecar, external_manifest)):
        raise PackageError('Output or sidecar already exists; choose a new output name')
    head = _git(repo, 'rev-parse', 'HEAD').decode('ascii').strip()
    tracked = set(_git(repo, 'ls-files', '-z').decode('utf-8').split('\0')) - {''}
    extras = {_relative(name) for name in include_new}
    if any(not _source_allowed(name) for name in extras):
        raise PackageError('--include-new cannot include excluded credentials/state/output')
    entries, excluded = {}, []
    for name in sorted(tracked | extras):
        if not _source_allowed(name):
            excluded.append(name)
            continue
        path = _regular_file(repo, name)
        entries['app/' + name] = path
    template = 'app/packaging/teacher/start.cmd'
    if template not in entries or 'app/scripts/teacher_launcher.py' not in entries:
        raise PackageError('Teacher launcher/template missing from tracked or --include-new sources')
    entries['一键启动.cmd'] = entries[template]
    for source, target in [('README.txt', '先读我.txt'), ('sample-product.txt', '示例产品资料.txt')]:
        name = 'app/packaging/teacher/' + source
        if name not in entries:
            raise PackageError(f'Teacher handoff file missing from source inventory: {source}')
        entries[target] = entries[name]
    for name, path in _site_files(site_packages):
        entries['python/Lib/site-packages/' + name] = path
    embed_bytes = embed.read_bytes()
    with zipfile.ZipFile(embed) as archive:
        if len(archive.infolist()) > 300 or sum(item.file_size for item in archive.infolist()) > 100 * 1024 * 1024:
            raise PackageError('Unexpected embeddable archive size')
        for item in archive.infolist():
            name = _relative(item.filename.rstrip('/'))
            if item.is_dir():
                raise PackageError('Unexpected directory in official embeddable archive')
            if item.flag_bits & 1 or stat.S_ISLNK(item.external_attr >> 16):
                raise PackageError('Encrypted/symlink embeddable member refused')
            if '/' in name or (Path(name).suffix.lower() not in {'.exe', '.dll', '.pyd', '.cat', '._pth'}
                               and name not in {'python312.zip', 'LICENSE.txt'}):
                raise PackageError('Unexpected file/state in official embeddable archive')
            target = 'python/' + name
            if target in entries:
                raise PackageError('Duplicate embeddable archive member')
            entries[target] = archive.read(item)
    for required in ('python.exe', 'python3.dll', 'python312.dll', 'python312.zip',
                     'python312._pth', '_sqlite3.pyd', 'sqlite3.dll', 'LICENSE.txt'):
        if 'python/' + required not in entries:
            raise PackageError(f'Incomplete embeddable archive: {required}')
    entries['python/python312._pth'] = b'python312.zip\n.\nLib/site-packages\n../app\nimport site\n'
    if len({name.casefold() for name in entries}) != len(entries):
        raise PackageError('Case-insensitive Windows package path collision')
    findings, preflight_hashes = [], {}
    for name, item in entries.items():
        data = item.read_bytes() if isinstance(item, Path) else item
        preflight_hashes[name] = hashlib.sha256(data).hexdigest()
        if _textual(name, data):
            findings.extend(secret_candidates(name, data))
    if findings:
        summary = ', '.join(f'{item["file"]}:{item["line"]} ({item["rule"]})' for item in findings[:20])
        raise PackageError(f'Secret candidates require review; no values printed: {summary}')
    dirty_paths = _git(repo, 'diff', 'HEAD', '--name-only', '-z').decode('utf-8').split('\0')
    status = _git(repo, 'status', '--porcelain=v1', '-z')
    manifest = {'format': 1, 'platform': 'windows-x64', 'source_commit': head,
                'source_dirty': bool(status), 'included_untracked': sorted(extras - tracked),
                'changed_tracked_paths': sorted(filter(None, dirty_paths)),
                'excluded_tracked_paths': excluded,
                'python_version': version, 'python_embed_sha256': hashlib.sha256(embed_bytes).hexdigest(),
                'python_embed_bytes': len(embed_bytes), 'files': {},
                'secret_scan': {'candidates': 0, 'reviewed_fixture_lines': {name: sorted(hashes) for name, hashes in REVIEWED_FIXTURE_LINES.items()},
                                'reviewed_library_sources': REVIEWED_LIBRARY_SOURCES,
                                'scope': 'UTF-8 textual source and dependency files; explicit test placeholders allowed; no OCR or credential validation'},
                'manifest_self_excluded': True, 'state_included': False,
                'verification': 'Build integrity only; native imports, launch and real workflow require separate acceptance.'}
    output.parent.mkdir(parents=True, exist_ok=True)
    created = []
    try:
        # Exclusive creation applies to both ZIP and sidecars, including races.
        handles = []
        try:
            for path in (output, sidecar, external_manifest):
                handle = path.open('xb')
                handles.append(handle)
                created.append(path)
        finally:
            for handle in handles:
                handle.close()
        with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for name, item in sorted(entries.items()):
                if isinstance(item, Path):
                    file_root = repo if item.is_relative_to(repo) and not item.is_relative_to(site_packages) else site_packages
                    _regular_file(file_root, item.relative_to(file_root).as_posix())
                data = item.read_bytes() if isinstance(item, Path) else item
                if hashlib.sha256(data).hexdigest() != preflight_hashes[name]:
                    raise PackageError('Input changed after secret preflight; retry with frozen inputs')
                archive.writestr(_zip_info(name), data)
                manifest['files'][name] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
            if _git(repo, 'rev-parse', 'HEAD').decode('ascii').strip() != head:
                raise PackageError('Source commit changed during packaging; rebuild from a frozen baseline')
            manifest_data = (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
            archive.writestr(_zip_info('MANIFEST.json'), manifest_data)
        # Re-read the completed archive, rather than trusting write-side hashes.
        with zipfile.ZipFile(output) as archive:
            for name, expected in manifest['files'].items():
                data = archive.read(name)
                if len(data) != expected['bytes'] or hashlib.sha256(data).hexdigest() != expected['sha256']:
                    raise PackageError('Completed archive content mismatch')
        with output.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        sidecar.write_text(f'{digest}  {output.name}\n', encoding='utf-8')
        external_manifest.write_bytes(manifest_data)
    except BaseException:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        raise
    return {'archive': str(output), 'bytes': output.stat().st_size, 'sha256': digest,
            'manifest': str(external_manifest), 'file_count': len(manifest['files']) + 1,
            'source_commit': head, 'source_dirty': manifest['source_dirty'], 'python_version': version}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=ROOT)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--python-embed', type=Path, required=True)
    parser.add_argument('--python-embed-version')
    parser.add_argument('--site-packages', type=Path, required=True)
    parser.add_argument('--include-new', action='append', default=[], metavar='REPO_RELATIVE_FILE')
    args = parser.parse_args()
    try:
        result = build(**vars(args))
    except (PackageError, OSError, zipfile.BadZipFile) as exc:
        # OS messages may include absolute local paths; never dump source contents.
        parser.exit(2, f'Packaging refused: {exc}\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
