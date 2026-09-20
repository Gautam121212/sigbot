#!/usr/bin/env bash
# One command to ship: npm run github
#
# Order matters and is not negotiable. Tests run BEFORE anything is committed,
# because a green Actions run on broken code is worse than a red one — it
# publishes the break to the live site. Pull comes before commit, because the
# scheduled ticks push ledger commits from GitHub's machines and committing on
# top of a stale local copy is what produced the rebase failures.
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
die() { printf '\n\033[31m%s\033[0m\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------- environment
[ -d .venv ] || die "no .venv here. Run: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
# shellcheck disable=SC1091
source .venv/bin/activate
[ -f .env ] && { set -a; # shellcheck disable=SC1091
                 source .env; set +a; }

# ---------------------------------------------------------------- 1. gates
say "1/6  Tests"
python -m pytest tests -q || die "tests failed — nothing was committed or pushed."

say "2/6  Lint and types"
if command -v ruff  >/dev/null 2>&1; then
  ruff check sigbot scripts tests --select F,E9,RUF019,PLR1736,B007 --no-cache \
    || die "ruff failed — nothing was committed."
fi
if command -v mypy >/dev/null 2>&1; then
  mypy sigbot --ignore-missing-imports || die "mypy failed — nothing was committed."
fi

# ---------------------------------------------------------------- 2. build
say "3/6  Rebuild the page"
python -m sigbot.runner publish
[ -f app/public/index.html ] || die "publish produced no app/public/index.html"
printf '     wrote app/public/index.html (%s KB)\n' \
  "$(( $(wc -c < app/public/index.html) / 1024 ))"

# ---------------------------------------------------------------- 3. sync
say "4/6  Pull (the scheduled ticks push from GitHub)"
# A fresh checkout, or a repo torn down and not yet re-created, has no git at
# all. Failing here with "not a git repository" told you nothing about what to
# do next, so say it instead.
git rev-parse --git-dir >/dev/null 2>&1 || die \
  "no git repository here. First time setup:
     git init
     git add . && git add -f shadow.db patterns.db watchlist.db \\
       opportunities.json universe.json paper.json
     git commit -m sigbot
   then publish it from GitHub Desktop (private), and rerun npm run github."

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if ! git remote get-url origin >/dev/null 2>&1; then
  echo "     no 'origin' remote yet — skipping pull and push."
  echo "     Publish the repo once from GitHub Desktop, then rerun."
  SKIP_REMOTE=1
fi
if [ -z "${SKIP_REMOTE:-}" ]; then
  git pull --rebase --autostash origin "$BRANCH" \
    || die "pull failed — resolve by hand, then rerun."
fi

# ---------------------------------------------------------------- 4. commit
say "5/6  Commit"
for f in shadow.db patterns.db watchlist.db opportunities.json universe.json \
         paper.json themes.json app/public/index.html; do
  git add -f "$f" 2>/dev/null || true
done
git add -A

# A secret reaching the repo is unrecoverable once pushed, so this is a hard
# stop rather than a warning.
if git diff --cached --name-only | grep -qE '(^|/)\.env$'; then
  die ".env is staged. Add it to .gitignore and unstage it before pushing."
fi

if git diff --cached --quiet; then
  echo "     nothing changed"
else
  MSG="${1:-ship: $(date -u '+%Y-%m-%d %H:%M UTC')}"
  git commit -m "$MSG"
  echo "     committed: $MSG"
fi

# ---------------------------------------------------------------- 5. push
say "6/6  Push"
if [ -n "${SKIP_REMOTE:-}" ]; then
  echo "     skipped — no remote. Publish from GitHub Desktop first."
else
  git push origin "HEAD:$BRANCH"
fi

# ---------------------------------------------------------------- 6. trigger
if command -v gh >/dev/null 2>&1; then
  say "Triggering the workflow"
  gh workflow run sigbot.yml --ref "$BRANCH" \
    && echo "     started — watch it: gh run watch" \
    || echo "     could not trigger; run it from the Actions tab"
else
  say "Done"
  echo "     gh CLI not installed, so the workflow was not triggered."
  echo "     Either run it from the Actions tab, or: brew install gh && gh auth login"
fi

printf '\n\033[32mShipped.\033[0m The next tick publishes from GitHub.\n'
