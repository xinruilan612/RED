"""Build a reproducible source archive without local data or credentials.

Only Git-tracked, currently existing files and explicit delivery additions are
eligible. Nothing is recovered from Git when the working-tree file is deleted.
The archive is a source delivery, not a database backup or an offline wheel set.
"""
import argparse
import hashlib
import json
import re
import subprocess
import zipfile
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
PREFIX = "youji-windtunnel"
ADDITIONS = (
    "backend/windtunnel.py", "backend/windtunnel_runtime.py",
    "frontend/windtunnel.js", "frontend/windtunnel.css",
    "scripts/package_windtunnel.py", "tests/test_windtunnel_domain.py",
    "tests/test_windtunnel_runtime.py", "tests/windtunnel_process_fixture.py",
    "tests/test_windtunnel_api.py", "tests/test_windtunnel_delivery.py",
    "tests/windtunnel_browser_check.cjs",
)
REQUIRED_SOURCES = (
    "requirements.txt", "backend/api.py", "backend/worker.py",
    "backend/windtunnel.py", "backend/windtunnel_runtime.py",
    "frontend/windtunnel.js", "frontend/windtunnel.css",
    "docs/windtunnel/DEPLOYMENT.md",
)
EXCLUDED_DIRS = {
    ".git", ".codex", ".agents", ".venv", "venv", "runtime", "output",
    "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache", "backups",
    "secrets", "credentials", "cookies", "sessions", "logs",
}
EXCLUDED_SUFFIXES = {".sqlite", ".sqlite3", ".db", ".pem", ".key", ".p12", ".pfx", ".pyc"}
SECRET_PATTERNS = (
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}"),
    re.compile(rb"\b(?:ghp|github_pat)_[A-Za-z0-9_]{25,}"),
    re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(rb"\bBearer[ \t]+[A-Za-z0-9_.-]{24,}"),
    re.compile(rb"postgres(?:ql)?://[^\s/:]+:[^\s/@]+@"),
)


def allowed_path(relative):
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts or not path.parts or "\\" in relative:
        return False
    lower = path.name.lower()
    if any(part.lower() in EXCLUDED_DIRS for part in path.parts):
        return False
    if lower.startswith(".env") and lower not in {".env.example", ".env.template"}:
        return False
    if lower in {".ds_store", "id_rsa", "id_ed25519", "id_ecdsa"}:
        return False
    if path.suffix.lower() in EXCLUDED_SUFFIXES or lower.endswith((".sqlite-wal", ".sqlite-shm", ".db-wal", ".db-shm")):
        return False
    return not re.search(r"(?:^|[._-])(?:secrets?|credentials?|cookies?|tokens?)(?:[._-]|$)", lower)


def candidates(root, extra=()):
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", "--cached"],
        check=True, capture_output=True,
    )
    selected = set(result.stdout.decode("utf-8").split("\0")) - {""}
    selected.update(ADDITIONS)
    for path in (root / 'docs/submission/evidence/baseline-source').rglob('*.snapshot'):
        selected.add(path.relative_to(root).as_posix())
    for path in (root / "docs/windtunnel").rglob("*"):
        if path.is_file() and path.suffix in {".md", ".csv", ".json", ".txt"}:
            selected.add(path.relative_to(root).as_posix())
    for relative in extra:
        if not allowed_path(relative):
            raise ValueError("Explicit inclusion uses a forbidden path")
        selected.add(relative)
    return sorted(selected)


def read_sources(root, extra=()):
    files = {}
    for relative in candidates(root, extra):
        if not allowed_path(relative):
            continue
        path = root / relative
        # Do not archive symlinks, including a regular file below a symlinked dir.
        if not path.is_file() or any(p.is_symlink() for p in [path, *path.parents] if p != root.parent):
            continue
        if not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("Source escapes repository: " + relative)
        data = path.read_bytes()
        if any(pattern.search(data) for pattern in SECRET_PATTERNS):
            raise ValueError("Potential credential detected; review file before packaging: " + relative)
        files[relative] = data
    for required in REQUIRED_SOURCES:
        if required not in files:
            raise ValueError("Required source missing: " + required)
    return files


def archive_entry(archive, name, data):
    info = zipfile.ZipInfo(PREFIX + "/" + name, (1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    archive.writestr(info, data)


def build(output, root=ROOT, extra=()):
    root = Path(root).resolve()
    output = Path(output).expanduser().resolve()
    files = read_sources(root, extra)
    products = (output, output.with_suffix(output.suffix + ".manifest.json"),
                output.with_suffix(output.suffix + ".sha256"), output.with_name(output.name + ".partial"))
    if any(product == (root / relative).resolve() for product in products for relative in files):
        raise ValueError("Output would overwrite an input source file")
    revision = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    manifest = {
        "format": 1,
        "package": PREFIX,
        "git_base_revision": revision,
        "source": "existing working-tree files; individual hashes are authoritative",
        "mode": "simulation by default; WINDTUNNEL_ALLOW_LIVE is not enabled",
        "files": {name: {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
                  for name, data in sorted(files.items())},
    }
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_name(output.name + ".partial")
    try:
        with zipfile.ZipFile(temp, "w") as archive:
            for name, data in sorted(files.items()):
                archive_entry(archive, name, data)
            archive_entry(archive, "DELIVERY_MANIFEST.json", manifest_bytes)
        with zipfile.ZipFile(temp) as archive:
            if archive.testzip() is not None:
                raise ValueError("Archive integrity check failed")
        temp.replace(output)
    finally:
        temp.unlink(missing_ok=True)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(output.suffix + ".manifest.json").write_bytes(manifest_bytes)
    output.with_suffix(output.suffix + ".sha256").write_text(digest + "  " + output.name + "\n", encoding="utf-8")
    return {"archive": str(output), "sha256": digest, "source_files": len(files), "bytes": output.stat().st_size}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "output/youji-windtunnel-source.zip")
    parser.add_argument("--include", action="append", default=[], metavar="RELATIVE_PATH",
                        help="Explicit additional source path; data/credential exclusions still apply")
    args = parser.parse_args()
    try:
        result = build(args.output, extra=args.include)
    except (ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, str(error) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
