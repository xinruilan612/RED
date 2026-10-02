#!/bin/sh
# macOS/Linux: this launcher never installs dependencies unless setup is requested.
set -eu
RED_PROJECT_DIR=$(CDPATH= cd -P "$(dirname "$0")" && pwd)
cd "$RED_PROJECT_DIR"
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

for RED_PROJECT_PYTHON in "$RED_PROJECT_DIR/runtime/venv/bin/python" "$RED_PROJECT_DIR/.venv/bin/python"; do
    if [ -x "$RED_PROJECT_PYTHON" ]; then
        exec "$RED_PROJECT_PYTHON" -X utf8 "$RED_PROJECT_DIR/scripts/local_dev.py" "$@"
    fi
done

for RED_PYTHON_NAME in python3.12 python3.13 python3.14 python3 python; do
    if RED_PROJECT_PYTHON=$(command -v "$RED_PYTHON_NAME") &&
       "$RED_PROJECT_PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' >/dev/null 2>&1; then
        exec "$RED_PROJECT_PYTHON" -X utf8 "$RED_PROJECT_DIR/scripts/local_dev.py" "$@"
    fi
done

printf '%s\n' 'Python 3.12 or newer is required. Install Python or prepare a project virtual environment.' >&2
exit 1
