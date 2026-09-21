# Make the priority queue drive the 3-hour tick

One edit on github.com. Nothing else changes.

1. github.com/Gautam121212/sigbot -> `.github` -> `workflows` -> `sigbot.yml`
2. Pencil icon (Edit)
3. Cmd+F, search for:  crypto15m news opportunities
4. That line lists the jobs the 3-hour tick runs. It looks like:

       jobs="resolve crypto15m news opportunities paper publish"

   Replace ONLY the part inside the quotes so it reads:

       jobs="priority-run paper publish"

5. Commit changes -> Commit directly to the master branch

Leave the daily (05:00) and weekly lines alone. `priority-run` already
includes resolve, so it is not repeated. `paper` and `publish` stay after
it because they must see what the queue produced.

To undo: put the original line back. Nothing is migrated or deleted.
