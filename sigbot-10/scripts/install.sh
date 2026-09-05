#!/usr/bin/env bash
# One-command setup. Safe to re-run: it will not overwrite your data.
#
#     bash scripts/install.sh
#
# Stops at the first real problem rather than carrying on and failing later
# somewhere confusing.

set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

say()  { printf "\n\033[1m%s\033[0m\n" "$1"; }
warn() { printf "  \033[33m! %s\033[0m\n" "$1"; }
die()  { printf "\n\033[31mSTOPPED: %s\033[0m\n" "$1"; exit 1; }

say "1/6  Where this is installed"
echo "  $ROOT"
case "$ROOT" in
  *"/Downloads/"*|*"/Documents/"*|*"/Desktop/"*)
    warn "This is inside a folder macOS protects."
    warn "It works when you run commands yourself, but a scheduled job will be"
    warn "denied and fail silently every night."
    warn "Recommended: mv '$ROOT' ~/sigbot   then re-run this from ~/sigbot"
    ;;
  *) echo "  good — not a protected folder" ;;
esac

say "2/6  Clearing the downloaded-from-internet flag"
if command -v xattr >/dev/null 2>&1; then
  xattr -dr com.apple.quarantine . 2>/dev/null || true
  echo "  done"
else
  echo "  not macOS, nothing to clear"
fi

say "3/6  Python"
command -v python3 >/dev/null 2>&1 || die "python3 not found. Install it from python.org"
PYV=$(python3 -c 'import sys;print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "  python3 $PYV"
python3 -c 'import sys;sys.exit(0 if sys.version_info>=(3,10) else 1)' \
  || die "Python $PYV is too old. Install 3.10 or newer from python.org"

say "4/6  Private package folder"
[ -d .venv ] || python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
echo "  active: $(python -c 'import sys;print(sys.prefix)')"

say "5/6  Installing packages"
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt
python -c "import numpy,pandas,sklearn,pytest,yfinance,feedparser" \
  || die "packages did not install correctly"
echo "  all present"

say "6/6  Running the test suite"
if python -m pytest tests -q 2>&1 | tail -3; then
  echo "  passed"
else
  die "tests failed. Send me the output above rather than continuing."
fi

say "Health check"
python -m sigbot.doctor || true

cat <<'NEXT'

--------------------------------------------------------------
Setup finished. Every new Terminal window needs this line first:

    source .venv/bin/activate

Then, once:

    python scripts/run_screen.py --provider yahoo --apply

That takes 10-20 minutes. After it finishes:

    python -m sigbot.runner daily
    python -m sigbot.runner publish
    open app/sigbot-report.html

To have it run itself every day:

    bash scripts/schedule.sh
--------------------------------------------------------------
NEXT
