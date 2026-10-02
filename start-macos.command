#!/bin/sh
# Finder/Terminal entry point; share the same guarded launcher with Linux.
set -eu
RED_PROJECT_DIR=$(CDPATH= cd -P "$(dirname "$0")" && pwd)
exec /bin/sh "$RED_PROJECT_DIR/start-unix.sh" "$@"
