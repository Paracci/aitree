#!/usr/bin/env bash
# AITree — one-line installer for Linux / macOS
# Usage: curl -fsSL https://raw.githubusercontent.com/paracci/aitree/main/install.sh | bash

set -euo pipefail

REPO="https://github.com/paracci/aitree"
MIN_PYTHON="3.10"

# ── Colour helpers ────────────────────────────────────────────────────────────
green()  { printf '\033[0;32m%s\033[0m\n' "$*"; }
yellow() { printf '\033[0;33m%s\033[0m\n' "$*"; }
red()    { printf '\033[0;31m%s\033[0m\n' "$*"; }
bold()   { printf '\033[1m%s\033[0m\n' "$*"; }

bold ""
bold "  ██████╗ ██╗████████╗██████╗ ███████╗███████╗"
bold "  ██╔══██╗██║╚══██╔══╝██╔══██╗██╔════╝██╔════╝"
bold "  ███████║██║   ██║   ██████╔╝█████╗  █████╗  "
bold "  ██╔══██║██║   ██║   ██╔══██╗██╔══╝  ██╔══╝  "
bold "  ██║  ██║██║   ██║   ██║  ██║███████╗███████╗"
bold "  ╚═╝  ╚═╝╚═╝   ╚═╝   ╚═╝  ╚═╝╚══════╝╚══════╝"
bold ""
echo  "  Project file map generator for AI-assisted development"
echo  "  $REPO"
echo  ""

# ── Check Python ──────────────────────────────────────────────────────────────
PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        ver=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
        if python3 -c "import sys; exit(0 if sys.version_info >= (3, 10) else 1)" 2>/dev/null || \
           "$cmd" -c "import sys; exit(0 if sys.version_info >= (3, 10) else 1)" 2>/dev/null; then
            PYTHON="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    red "✗  Python ${MIN_PYTHON}+ not found."
    echo "   Install it from https://python.org and re-run this script."
    exit 1
fi

green "✔  Python $($PYTHON --version) found"

# ── Install ───────────────────────────────────────────────────────────────────
echo ""
echo "Installing AITree via pip..."
"$PYTHON" -m pip install --upgrade "git+${REPO}.git[git]" --quiet

echo ""
green "✔  AITree installed successfully!"
echo ""
echo "  Quick start:"
echo "    aitree .              # print tree of current directory"
echo "    aitree . --save       # save to _aitree.txt"
echo "    aitree . --live       # watch for changes (requires: pip install watchdog)"
echo ""
echo "  Verify:"
echo "    aitree --version"
echo ""
