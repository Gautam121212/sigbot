# Setting this up — start here

Written for someone who has not used Terminal before.

## Where to put it

**`~/sigbot`** — that is your home folder, the one with your name on it in
Finder. `~` is shorthand for it. Not a subfolder, the folder itself.

Where it goes matters more than you would expect:

| Location | Verdict |
|---|---|
| `~/sigbot` (home folder) | **Right.** Not protected, always mounted, never synced |
| `~/Downloads/sigbot` | Scheduled jobs are blocked. Fails silently every night |
| `~/Documents/sigbot`, `~/Desktop/sigbot` | Same, and these often sync to iCloud too |
| iCloud Drive | **Worst.** iCloud offloads files and leaves a placeholder, so the databases vanish mid-run and come back later |
| An external drive | Fails whenever it is unmounted, and some drives sleep on their own |
| `/tmp` | macOS deletes it, and your whole record with it |

The reason is that macOS guards Downloads, Documents and Desktop. Running
commands yourself works fine — the permission prompt goes to you. A background
job has nobody to ask, so it is denied, and you find out from a gap in the
record weeks later.

The home folder root has none of these problems. `python -m sigbot.doctor`
checks which of them you are in.

---

## Step 1 — Open Terminal

Press `Cmd` + `Space`, type `terminal`, press Return.

## Step 2 — Move the folder to the right place

Unzip `sigbot.zip`. Then:

```bash
mv ~/Downloads/sigbot ~/sigbot
cd ~/sigbot
```

If the unzipped folder is somewhere else, drag it onto the Terminal window after
typing `mv ` to fill in its path.

## Step 3 — Run the installer

```bash
bash scripts/install.sh
```

This does everything: clears the "downloaded from the internet" flag macOS puts
on the files, checks your Python version, builds a private package folder,
installs what is needed, runs all 384 tests, and finishes with a health check.

It stops at the first real problem rather than carrying on and failing later
somewhere confusing. If it stops, send me what it printed.

Takes about five minutes.

## Step 4 — Pick the 100 it will watch

Every new Terminal window needs this line first:

```bash
source .venv/bin/activate
```

Then:

```bash
python scripts/run_screen.py --provider yahoo --apply
```

**Takes 10-20 minutes.** It downloads price history for 156 candidates and picks
the best 100. Lines like `skip XYZ: RuntimeError` are normal — Yahoo refuses some
symbols. The total is reported at the end, so a thin result says it is thin.

The last line should read `Board set: 100 added`. **If it says `0 added`, stop
and tell me** — it means something else filled the board first.

## Step 5 — First run

```bash
python -m sigbot.runner daily
python -m sigbot.runner publish
open app/sigbot-report.html
```

`daily` makes predictions. `publish` draws the charts and builds the page.

**Do not skip publish.** The zip ships with a sample page so you can see the
layout before you have data. It is marked SAMPLE DATA at the top, and `publish`
replaces it with yours.

## Step 6 — Check it is actually working

```bash
python -m sigbot.doctor
```

Goes through fifteen checks and tells you exactly what to do about anything
wrong. Run it any time something looks off.

## Step 7 — Make it run itself

```bash
bash scripts/schedule.sh
```

Runs every day at 20:30: scores yesterday's predictions, makes today's, rebuilds
the page. On Mondays it also re-screens and rotates the board.

```bash
tail -f logs/daily.log        # watch it
launchctl start com.sigbot.daily   # run it now
bash scripts/schedule.sh remove    # stop it
```

If the Mac is asleep at 20:30 the job runs when it next wakes. If it is shut
down, that day is skipped. Sleep is fine; shutdown is not.

## Step 8 — Onto your iPhone

1. Finder → `sigbot` → `app`
2. Right-click `sigbot-report.html` → Share → AirDrop → your iPhone
3. Tap the notification

To give it an icon: with it open in Safari, tap Share → "Add to Home Screen".

Every screen works with no internet. Tap a model for its record, an asset for
its chart and what the indicators say.

Re-send the file whenever you want fresh numbers. Or set up messages instead:

```bash
python -m sigbot.setup_delivery --telegram    # the steps
python -m sigbot.setup_delivery --chatid      # finds your chat id
python -m sigbot.setup_delivery --test        # sends a test message
```

Two things worth knowing before you start:

**Never paste the token into a browser.** A token is the only thing needed to
control the bot. In an address bar it lands in history, in sync across your
devices, and in any screenshot of that window. `--chatid` does the same job
from the terminal and never prints it.

**Your bot will never reply to you.** It has no code behind it — it is a
one-way pipe your Mac pushes messages through. Silence after you message it is
normal, not a fault.

---

## If macOS gets in the way

| What happens | Why, and what to do |
|---|---|
| A scheduled job never runs | The folder is in Downloads or Documents. Move it to `~/sigbot` |
| "cannot be opened because it is from an unidentified developer" | Not for Python files. If it appears: `xattr -dr com.apple.quarantine ~/sigbot` |
| A permissions box appears on the first scheduled run | Allow it. If you miss it: System Settings → Privacy & Security → Full Disk Access → add Terminal |
| Nothing runs overnight | The Mac was shut down, not asleep. Sleep is fine |
| `externally-managed-environment` | You skipped the venv. Run `bash scripts/install.sh` |

## Other things that go wrong

| What you see | What it means |
|---|---|
| `No module named pandas` or `pytest` | You forgot `source .venv/bin/activate` |
| `No such file or directory` | Run `cd ~/sigbot` first |
| `Board set: 0 added` | Something pre-filled the board. `rm -f watchlist.db` and re-run Step 4 |
| The page says SAMPLE DATA | You have not run `publish` yet |
| `possibly delisted; no price data` | Yahoo rate limiting. It retries three times, then skips and counts it |
| Everything is amber | Correct. Nothing has been measured yet |
| The page is blank on iPhone | You opened `index.html`. Use `sigbot-report.html` |
| `{"ok":true,"result":[]}` from Telegram | The bot got no messages. You probably messaged @BotFather instead of your own bot. Run `--chatid` for the full checklist |
| The bot does not reply | Expected. It has no code behind it and never answers |

---

## What to expect, honestly

**Week 1** — everything amber. Predictions are being made and scored; nothing
has enough record to say anything.

**Month 1** — the Learned and Missed tabs fill up. You can see what it got right
and wrong, and why.

**Month 3-6** — a few assets may reach 60+ checks. Some go green. Most do not,
and several get dropped and replaced.

If nothing is ever green, that is a real answer rather than a failure. It means
the edge was not there — and finding that out for the cost of some electricity
beats finding it out with money.
