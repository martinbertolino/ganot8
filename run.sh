#!/usr/bin/env bash
# Launch Ganot8 from source, bootstrapping the venv on first run.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

PYENV_VERSION_WANTED="$(cat .python-version)"
VENV=".venv"

find_base_python() {
    local root="${PYENV_ROOT:-$HOME/.pyenv}"
    local candidate="$root/versions/$PYENV_VERSION_WANTED/bin/python3"
    if [[ -x "$candidate" ]]; then echo "$candidate"; return 0; fi
    if command -v pyenv >/dev/null 2>&1; then
        candidate="$(pyenv root)/versions/$PYENV_VERSION_WANTED/bin/python3"
        if [[ -x "$candidate" ]]; then echo "$candidate"; return 0; fi
    fi
    echo "ganot8: Python $PYENV_VERSION_WANTED not found." >&2
    echo "  Install it with:  pyenv install $PYENV_VERSION_WANTED" >&2
    return 1
}

if [[ ! -x "$VENV/bin/python" ]]; then
    base="$(find_base_python)"
    echo "ganot8: creating $VENV using $base" >&2
    "$base" -m venv "$VENV"
    "$VENV/bin/pip" install --quiet --upgrade pip
    echo "ganot8: installing dependencies (pygobject/pycairo compile, this takes a minute)" >&2
    if ! "$VENV/bin/pip" install --quiet -r requirements.txt; then
        echo "ganot8: dependency install failed." >&2
        echo "  Most likely missing build deps. Try:" >&2
        echo "    sudo dnf install cairo-gobject-devel glib2-devel cairo-devel libffi-devel gcc" >&2
        rm -rf "$VENV"
        exit 1
    fi
fi

# Compile the GSettings schema if it is missing or out of date. Without it
# the application still runs, it just will not remember anything.
SCHEMA_DIR="data/schemas"
if command -v glib-compile-schemas >/dev/null 2>&1; then
    if [[ ! -f "$SCHEMA_DIR/gschemas.compiled" ]] \
       || [[ "$SCHEMA_DIR/io.github.martinb.Ganot8.gschema.xml" -nt "$SCHEMA_DIR/gschemas.compiled" ]]; then
        glib-compile-schemas "$SCHEMA_DIR" || \
            echo "ganot8: schema compile failed; settings will not persist" >&2
    fi
fi

export PYTHONPATH="src${PYTHONPATH:+:$PYTHONPATH}"
exec "$VENV/bin/python" -m ganot8 "$@"
