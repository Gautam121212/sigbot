# Workflow change — what should be in your sigbot.yml

Go to: github.com/Gautam121212/sigbot -> .github -> workflows -> sigbot.yml
Click the pencil icon to edit.

---

STEP 1 — THE 3-HOUR TICK (runs every three hours, 24/7)
Find the line that starts with:  jobs=
under the cron that fires every 3 hours (it fires 8 times a day).

It should read:
    jobs="priority-run paper publish"

If yours says something different, change only the part inside the quotes.

---

STEP 2 — THE WEEKDAY DAILY TICK (runs once a day after the US close)
Find the line under the daily cron.

It should read:
    jobs="stocks contagion resolve paper publish"

If yours says something different, change only the part inside the quotes.

---

STEP 3 — THE WEEKLY CYCLE
Leave the weekly cycle line exactly as it is.

---

WHY RESOLVE MUST BE IN THE DAILY TICK:
resolve scores forecasts against the closing price. It must run after
every session, not once a week. Without it, forecasts pile up unscored.

Currently 1,494 forecasts are past due and unscored because resolve was
never in the workflow. They will score on the next tick that includes it.

---

SAFE AT ANY TIME: the old job names daily and setups now run the stocks
scan, so an unedited workflow line still works.
