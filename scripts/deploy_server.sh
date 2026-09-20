#!/usr/bin/env bash
# Set up sigbot on an Oracle Cloud Always Free VM (Ubuntu ARM).
#
# Copy this to the server and run it there:
#
#     scp scripts/deploy_server.sh ubuntu@YOUR_IP:~
#     ssh ubuntu@YOUR_IP
#     bash deploy_server.sh
#
# It stops before installing anything if Yahoo will not serve this IP, because
# that is the one failure that makes the whole migration pointless and it is
# invisible until you test it.

set -euo pipefail

say() { printf "\n\033[1m%s\033[0m\n" "$1"; }
die() { printf "\n\033[31mSTOPPED: %s\033[0m\n" "$1"; exit 1; }

say "1/7  Where am I"
uname -a
[ -f /etc/os-release ] && . /etc/os-release && echo "  $PRETTY_NAME"
free -m 2>/dev/null | awk '/Mem:/ {print "  RAM: " $2 " MB"}'
df -h / | awk 'NR==2 {print "  disk free: " $4}'

say "2/7  Python"
sudo apt-get update -qq
sudo apt-get install -y -qq python3 python3-venv python3-pip build-essential
python3 --version
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' \
  || die "Python is older than 3.10. Pick a newer Ubuntu image."

say "3/7  Can this IP actually get market data?"
# The decisive test. Datacenter addresses are rate-limited and sometimes
# blocked outright by Yahoo, far more aggressively than home connections. If
# this fails, nothing else about the migration matters.
python3 -m venv /tmp/probe
/tmp/probe/bin/pip install --quiet yfinance
cat > /tmp/probe_test.py <<'PROBE'
import sys
import yfinance as yf

results = {}
for symbol in ("AAPL", "RELIANCE.NS", "BTC-USD"):
    try:
        bars = yf.download(symbol, period="1mo", progress=False, threads=False)
        results[symbol] = len(bars)
    except Exception as exc:
        results[symbol] = f"{type(exc).__name__}: {exc}"

for symbol, outcome in results.items():
    print(f"  {symbol:<14} {outcome}")

usable = sum(1 for v in results.values() if isinstance(v, int) and v > 10)
print(f"\n  {usable} of 3 symbols returned usable history.")
sys.exit(0 if usable >= 2 else 1)
PROBE
if ! /tmp/probe/bin/python /tmp/probe_test.py; then
  rm -rf /tmp/probe /tmp/probe_test.py
  die "Yahoo will not serve this address. Nothing was installed.

  This is the failure that makes the migration pointless, and it is why the
  test runs before the work rather than after. Options:
    - try a different Oracle region; blocks are per-IP-range
    - keep it on the Mac and accept the overnight gaps
    - pay for a data source that welcomes servers"
fi
rm -rf /tmp/probe /tmp/probe_test.py
echo "  data access works from this address"

say "4/7  Files"
if [ ! -d "$HOME/sigbot" ]; then
  die "~/sigbot is not here. Copy it up first, from your Mac:

    cd ~ && tar czf sigbot.tgz --exclude=.venv --exclude='*.db' sigbot
    scp sigbot.tgz ubuntu@THIS_SERVER:~
    ssh ubuntu@THIS_SERVER 'tar xzf sigbot.tgz'

  Leave the .db files out. Starting the ledger fresh is cleaner than merging
  two of them, and you lose only a couple of days."
fi
cd "$HOME/sigbot"
echo "  found $(ls sigbot/*.py | wc -l) modules"

say "5/7  Install"
python3 -m venv .venv
./.venv/bin/pip install --quiet --upgrade pip
./.venv/bin/pip install --quiet -r requirements.txt
./.venv/bin/python -c "import numpy, pandas, sklearn, yfinance, feedparser" \
  || die "packages did not install"
echo "  installed"

say "6/7  Tests"
./.venv/bin/python -m pytest tests -q 2>&1 | tail -3 \
  || die "tests failed — do not schedule a system that does not pass them"

say "7/7  Run it as a service"
mkdir -p "$HOME/sigbot/logs"
sudo tee /etc/systemd/system/sigbot.service >/dev/null <<UNIT
[Unit]
Description=sigbot coordinator
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$HOME/sigbot
EnvironmentFile=$HOME/sigbot/.env
ExecStart=$HOME/sigbot/.venv/bin/python -m sigbot.coordinator
Restart=always
RestartSec=60
StandardOutput=append:$HOME/sigbot/logs/coordinator.log
StandardError=append:$HOME/sigbot/logs/coordinator.log

[Install]
WantedBy=multi-user.target
UNIT

if [ ! -f "$HOME/sigbot/.env" ]; then
  cat <<'ENVNOTE'

  No .env here yet. systemd reads it for the Telegram credentials, and the
  service will not start without it. From your Mac:

    scp ~/sigbot/.env ubuntu@THIS_SERVER:~/sigbot/.env

  Then:  sudo systemctl enable --now sigbot

ENVNOTE
  exit 0
fi

sudo systemctl daemon-reload
sudo systemctl enable --now sigbot
sleep 5
sudo systemctl status sigbot --no-pager | head -12

cat <<'NEXT'

Running, and it restarts itself on failure and on reboot.

  is it alive?   systemctl status sigbot
  watch it       tail -f ~/sigbot/logs/coordinator.log
  task table     cd ~/sigbot && ./.venv/bin/python -m sigbot.coordinator --status
  stop it        sudo systemctl stop sigbot

On your Mac, turn the local one off so you are not running two:

  bash scripts/autostart.sh remove
  bash scripts/lidclosed.sh off

Two things about the server that differ from the Mac:

  1. Free tier instances get reclaimed if idle for weeks. This one will not be
     idle, but log in occasionally so Oracle sees activity.
  2. The report file lives on the server now. It reaches your phone through
     Telegram exactly as before — nothing changes there.
NEXT
