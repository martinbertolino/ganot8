#!/usr/bin/env bash
# Run the test suite, under a virtual display when one is needed.
#
# 101 of the tests build real GTK widgets and skip themselves when there is no
# display (docs/SPEC.md section 11). Skipping is silent, so a run with no
# display looks green while testing none of the UI. This script makes that
# impossible to miss, and --strict turns it into a failure.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

STRICT=0
ARGS=()
for arg in "$@"; do
    case "$arg" in
        --strict) STRICT=1 ;;
        *) ARGS+=("$arg") ;;
    esac
done

if [[ ! -x .venv/bin/pytest ]]; then
    echo "run-tests: no .venv yet - run ./run.sh once to bootstrap it" >&2
    exit 1
fi

# One source of truth with the test suite: tests/support.py. Gtk.init_check()
# must not be used here - it returns True with no display, and has been seen to
# segfault outright, which would make this script crash instead of answering.
have_display() {
    .venv/bin/python -c "
import sys
sys.path.insert(0, 'tests')
from support import display_available
raise SystemExit(0 if display_available() else 1)
" 2>/dev/null
}

if have_display; then
    exec .venv/bin/pytest "${ARGS[@]+"${ARGS[@]}"}"
fi

if command -v xvfb-run >/dev/null 2>&1; then
    echo "run-tests: no display; using xvfb-run" >&2
    exec xvfb-run -a .venv/bin/pytest "${ARGS[@]+"${ARGS[@]}"}"
fi

cat >&2 <<'WARNING'
=============================================================================
run-tests: NO DISPLAY AND NO XVFB

  The 4 widget test modules (test_tools, test_core_tools, test_window,
  test_centering) will skip themselves. That is 101 tests, about 40% of the
  suite, and the run will still report success.

  Install it with:   sudo dnf install xorg-x11-server-Xvfb
=============================================================================
WARNING

if (( STRICT )); then
    echo "run-tests: --strict given, refusing to run a partial suite" >&2
    exit 2
fi
exec .venv/bin/pytest "${ARGS[@]+"${ARGS[@]}"}"
