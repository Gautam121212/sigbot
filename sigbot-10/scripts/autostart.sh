#!/usr/bin/env bash
# Make the coordinator start itself and stay running.
#
#     bash scripts/autostart.sh          install
#     bash scripts/autostart.sh remove   uninstall
#     bash scripts/autostart.sh status   is it alive?
#
# Answering the question directly: before this, nothing started on its own. You
# ran commands by hand, or launchd fired a one-shot job at a fixed time and
# exited. This installs the coordinator as a long-running agent that:
#
#   starts when you log in                     RunAtLoad
#   restarts within 10s if it dies or is killed  KeepAlive
#   keeps the Mac awake while it runs           caffeinate -s
#
# The last one matters more than it sounds. Without it the laptop sleeps, the
# process freezes, and the gap looks like a quiet market rather than a shut lid.

set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
LABEL="com.sigbot.coordinator"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

case "${1:-install}" in
  remove)
    launchctl unload "$PLIST" 2>/dev/null || true
    rm -f "$PLIST"
    echo "Autostart removed. Nothing runs on its own now."
    exit 0 ;;
  status)
    if launchctl list 2>/dev/null | grep -q "$LABEL"; then
      echo "Running:"; launchctl list | grep "$LABEL"
      echo; tail -5 "$ROOT/logs/coordinator.log" 2>/dev/null || true
    else
      echo "Not running. Install with: bash scripts/autostart.sh"
    fi
    exit 0 ;;
esac

[ "$(uname)" = "Darwin" ] || { echo "macOS only. On Linux use a systemd unit."; exit 1; }
[ -x "$ROOT/.venv/bin/python" ] || { echo "No .venv. Run: bash scripts/install.sh"; exit 1; }

case "$ROOT" in
  *"/Downloads/"*|*"/Documents/"*|*"/Desktop/"*)
    echo "WARNING: $ROOT is inside a folder macOS protects."
    echo "A background agent cannot read it without Full Disk Access, and it"
    echo "will fail silently. Move it first:  mv '$ROOT' ~/sigbot"
    read -r -p "Install anyway? [y/N] " reply
    [ "$reply" = "y" ] || exit 1 ;;
esac

# Preflight. An earlier version loaded the plist and reported success without
# checking the thing it was about to run, so a missing import became a crash
# loop restarting every 60 seconds while looking healthy.
echo "Checking the coordinator can start..."
if ! "$ROOT/.venv/bin/python" -m sigbot.coordinator --status >/tmp/sigbot_preflight 2>&1; then
  echo ""
  echo "It cannot. Nothing was installed."
  echo ""
  sed 's/^/  /' /tmp/sigbot_preflight | tail -12
  rm -f /tmp/sigbot_preflight
  exit 1
fi
rm -f /tmp/sigbot_preflight
echo "  starts cleanly"

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
    <!-- caffeinate -s holds off system sleep for as long as the child runs.
         Without it the laptop sleeps and the gap reads as a quiet market. -->
    <string>/usr/bin/caffeinate</string>
    <string>-s</string>
    <string>$ROOT/.venv/bin/python</string>
    <string>-m</string>
    <string>sigbot.coordinator</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key>
  <dict>
    <key>SuccessfulExit</key><false/>
    <key>Crashed</key><true/>
  </dict>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>StandardOutPath</key><string>$ROOT/logs/coordinator.log</string>
  <key>StandardErrorPath</key><string>$ROOT/logs/coordinator.log</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PYTHONUNBUFFERED</key><string>1</string>
  </dict>
</dict>
</plist>
PLIST_END

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

# launchctl registers asynchronously. Looking once, three seconds in, reported
# failure for services that were merely slow.
listed=""
for _ in 1 2 3 4 5 6; do
  sleep 2
  if launchctl list 2>/dev/null | grep -q "$LABEL"; then listed="yes"; break; fi
done
if [ -z "$listed" ]; then
  echo "Loaded, but launchctl does not list it after 12 seconds."
  tail -20 "$ROOT/logs/"*.log 2>/dev/null | sed 's/^/  /' || true
  exit 1
fi
sleep 3

cat <<NEXT

Installed and started. It now runs on its own.

  is it alive?    bash scripts/autostart.sh status
  watch it        tail -f logs/coordinator.log
  task table      python -m sigbot.coordinator --status
  stop it         bash scripts/autostart.sh remove

Two things to know:

  1. Credentials. launchd does not inherit your shell, so the coordinator
     reads ~/sigbot/.env. If you have not written one:
         printf 'TELEGRAM_TOKEN=%s\nTELEGRAM_CHAT_ID=%s\n' \\
           "\$TELEGRAM_TOKEN" "\$TELEGRAM_CHAT_ID" > .env && chmod 600 .env

  2. Sleep. caffeinate stops the system sleeping, but closing the lid on a
     MacBook still suspends it. Gaps are recorded either way, so read them
     rather than assuming a quiet stretch was a quiet market.
NEXT
