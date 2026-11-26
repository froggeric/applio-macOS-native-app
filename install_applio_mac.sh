#!/bin/bash
# Creates venv_macos for the native macOS app and installs its dependencies.
#
#   ./install_applio_mac.sh               Python 3.12 (what upstream targets)
#   ./install_applio_mac.sh --python 3.12.9
#
# Needs macOS on Apple Silicon and either uv (recommended) or a python3.12 on
# PATH. ffmpeg is optional: only the "light cleanup" preprocessing option uses
# it (brew install ffmpeg).
#
# Then:
#   source venv_macos/bin/activate
#   python build_macos.py
set -euo pipefail

VENV_DIR="venv_macos"
PYTHON_SPEC="3.12"
REQUIREMENTS="requirements_macos.txt"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --python)
            [[ $# -ge 2 ]] || { echo "--python needs a version or path" >&2; exit 2; }
            PYTHON_SPEC="$2"
            shift 2
            ;;
        -h|--help)
            sed -n '2,15p' "$0"
            exit 0
            ;;
        *)
            echo "Unknown argument: $1 (try --help)" >&2
            exit 2
            ;;
    esac
done

if [[ "$(uname)" != "Darwin" ]]; then
    echo "Error: this script is for macOS only." >&2
    exit 1
fi
if [[ ! -f "$REQUIREMENTS" ]]; then
    echo "Error: $REQUIREMENTS not found. Run this from the repository root." >&2
    exit 1
fi

if [[ -d "$VENV_DIR" && ! -x "$VENV_DIR/bin/python" ]]; then
    echo "Error: $VENV_DIR exists but has no bin/python. Remove it and re-run." >&2
    exit 1
fi

if [[ -d "$VENV_DIR" ]]; then
    echo "Using existing $VENV_DIR"
elif command -v uv >/dev/null 2>&1; then
    echo "Creating $VENV_DIR with uv (Python $PYTHON_SPEC)..."
    uv venv "$VENV_DIR" --python "$PYTHON_SPEC"
else
    if [[ "$PYTHON_SPEC" == */* || -x "$PYTHON_SPEC" ]]; then
        PYTHON_BIN="$PYTHON_SPEC"
    else
        PYTHON_BIN="$(command -v "python$PYTHON_SPEC" || true)"
    fi
    if [[ -z "${PYTHON_BIN:-}" ]]; then
        echo "Error: no Python $PYTHON_SPEC found. Install uv (brew install uv) or" >&2
        echo "provide python$PYTHON_SPEC on PATH, or pass --python /path/to/python." >&2
        exit 1
    fi
    echo "Creating $VENV_DIR with $PYTHON_BIN..."
    "$PYTHON_BIN" -m venv "$VENV_DIR"
    "$VENV_DIR/bin/python" -m pip install --upgrade pip
fi

echo "Installing $REQUIREMENTS..."
if command -v uv >/dev/null 2>&1; then
    uv pip install --python "$VENV_DIR/bin/python" -r "$REQUIREMENTS"
else
    "$VENV_DIR/bin/python" -m pip install -r "$REQUIREMENTS"
fi

echo
echo "Done. Python in $VENV_DIR: $("$VENV_DIR/bin/python" -c 'import sys; print(sys.version.split()[0])')"
echo "Next:"
echo "  source $VENV_DIR/bin/activate"
echo "  python build_macos.py                   # build dist/Applio.app"
echo "  python applio_launcher.py               # run the app from source"
