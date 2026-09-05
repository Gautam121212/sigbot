#!/usr/bin/env bash
# Keep the Mac awake with the lid closed.
#
#     bash scripts/lidclosed.sh          turn it on
#     bash scripts/lidclosed.sh status   what is set right now
#     bash scripts/lidclosed.sh off      put it back
#
# `caffeinate`, which autostart.sh already uses, blocks idle sleep but not
# lid-close sleep. That is why the coordinator still stops when you shut the
# laptop. Only `pmset disablesleep` changes that, it needs sudo, and it is a
# system-wide setting rather than anything belonging to this project.
#
# THE HAZARD, PLAINLY
#
# A MacBook with sleep disabled, lid shut, inside a bag has no airflow. It
# heats, throttles, and lithium cells age faster warm. Machines have been
# ruined this way. On a desk this is fine; in a bag it is not, and no software
# check can tell the difference — only you know where the laptop is.
#
# `off` reverses it completely. Run that before the laptop travels.

set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

[ "$(uname)" = "Darwin" ] || { echo "macOS only."; exit 1; }

show_state() {
  local disabled power
  disabled=$(pmset -g | awk '/SleepDisabled/ {print $2}')
  power=$(pmset -g batt | head -1)
  echo "  SleepDisabled : ${disabled:-0}  (1 = stays awake with the lid shut)"
  echo "  Power         : $power"
  if pgrep -f "sigbot.coordinator" >/dev/null 2>&1; then
    echo "  Coordinator   : running"
  else
    echo "  Coordinator   : NOT running — bash scripts/autostart.sh"
  fi
}

case "${1:-on}" in
  status)
    echo "Current state:"
    show_state
    exit 0 ;;
  off)
    echo "Restoring normal sleep. The Mac will suspend when you close the lid,"
    echo "and the coordinator will stop until you open it again."
    sudo pmset -a disablesleep 0
    echo ""
    show_state
    exit 0 ;;
esac

cat <<'WARNING'
This disables lid-close sleep for the whole system, not just for sigbot.

  On a desk, plugged in            fine
  In a bag while still running     do not. No airflow, it will cook.

Reverse it any time with:  bash scripts/lidclosed.sh off
Run that before the laptop travels.

WARNING

# Battery is the one thing worth refusing on. Lid shut, unplugged, sleep
# disabled is the worst case: it runs until flat and gets warm doing it.
if ! pmset -g batt | grep -q "AC Power"; then
  echo "You are on battery. Disabling sleep now would run the machine flat"
  echo "and warm it up with the lid shut."
  read -r -p "Plug in first, or continue anyway? [continue/N] " reply
  [ "$reply" = "continue" ] || { echo "Nothing changed."; exit 1; }
fi

read -r -p "Type 'yes' to disable lid-close sleep: " confirm
[ "$confirm" = "yes" ] || { echo "Nothing changed."; exit 1; }

sudo pmset -a disablesleep 1

echo ""
echo "Done. The Mac now stays awake with the lid closed."
echo ""
show_state
cat <<'NEXT'

Two things to check after your first lid-closed night:

  bash scripts/autostart.sh status         still running?
  python -m sigbot.coordinator --status    gaps should stay at zero

A non-zero gap count means it slept anyway — which happens if macOS decides
the machine is too hot, or if something else re-enabled sleep.

If the laptop needs to travel:

  bash scripts/lidclosed.sh off
NEXT
