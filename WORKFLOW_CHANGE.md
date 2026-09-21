# Workflow change — two lines on GitHub

1. github.com/Gautam121212/sigbot -> `.github` -> `workflows` -> `sigbot.yml`
2. Pencil icon (Edit)
3. Cmd+F, search:  crypto15m news opportunities
   Change the text inside the quotes to:
       jobs="priority-run paper publish"
4. Cmd+F, search:  daily contagion
   Change the text inside the quotes to:
       jobs="stocks contagion resolve paper publish"
5. Leave the weekly `cycle` line alone.
6. Commit changes -> Commit directly to the master branch

If a search finds nothing or the line looks different, stop and paste the
surrounding lines rather than guessing.

Why: stocks and follow-on moves read DAILY bars, so they run once a day after
the close. News, crypto and opportunities decay in hours, so they run every
3 hours in order of urgency. Scanning 675 names every 3 hours would redo the
same work eight times a day and is the likeliest cause of a timeout.

Safe in either order: the old job names `daily` and `setups` now run the
stocks scan, so an unedited workflow keeps working.

To undo: put the original lines back.
