#!/usr/bin/env bash
# Make it run itself, every day, on macOS.
#
#     bash scripts/schedule.sh          install the schedule
#     bash scripts/schedule.sh remove   take it out again
#
# Uses launchd rather than cron. cron still exists on macOS but Apple has been
# retiring it for years, and — the part that matters — a launchd job that misses
# its slot because the Mac was asleep runs as soon as it wakes. A cron job just
# does not run that day, and you find out from a gap in the record.

set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
LABEL="com.sigbot.daily"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

if [ "${1:-}" = "remove" ]; then
  launchctl unload "$PLIST" 2>/dev/null || true
  rm -f "$PLIST"
  echo "Schedule removed."
  exit 0
fi

[ "$(uname)" = "Darwin" ] || { echo "This script is for macOS. On Linux use cron."; exit 1; }
[ -x "$ROOT/.venv/bin/python" ] || { echo "No .venv found. Run: bash scripts/install.sh"; exit 1; }

case "$ROOT" in
  *"/Downloads/"*|*"/Documents/"*|*"/Desktop/"*)
    echo "WARNING: $ROOT is inside a folder macOS protects."
    echo "A background job cannot read it without Full Disk Access, and it will"
    echo "fail silently every night. Move the folder to ~/sigbot first:"
    echo "    mv '$ROOT' ~/sigbot && cd ~/sigbot && bash scripts/schedule.sh"
    read -r -p "Install anyway? [y/N] " reply
    [ "$reply" = "y" ] || exit 1
    ;;
esac

mkdir -p "$HOME/Library/LaunchAgents" "$ROOT/logs"

cat > "$PLIST" <<PLIST_END
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>ProgramArguments</key>
  <array>
    <string>$ROOT/.venv/bin/python</string>
    <string>$ROOT/scripts/daily_job.py</string>
  </array>
  <key>StartCalendarInterval</key>
  <array>
    <dict><key>Hour</key><integer>20</integer><key>Minute</key><integer>30</integer></dict>
  </array>
  <!-- Catches up after the Mac has been asleep, which cron would not. -->
  <key>RunAtLoad</key><false/>
  <key>StandardOutPath</key><string>$ROOT/logs/daily.log</string>
  <key>StandardErrorPath</key><string>$ROOT/logs/daily.log</string>
</dict>
</plist>
PLIST_END

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

cat <<NEXT

Scheduled: every day at 20:30, writing to logs/daily.log

  see it listed     launchctl list | grep sigbot
  run it now        launchctl start $LABEL
  watch the log     tail -f logs/daily.log
  remove it         bash scripts/schedule.sh remove

Two things macOS will do to you if you let it:

  1. If the Mac is asleep at 20:30 the job runs when it next wakes. If it is
     shut down, that day is skipped. Sleep is fine; shutdown is not.
  2. The first run may raise a permissions prompt. Allow it. If you miss the
     prompt, go to System Settings > Privacy & Security > Full Disk Access and
     add Terminal.
NEXT
