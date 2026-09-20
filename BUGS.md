# BUGS.md — the regression registry

Every bug that has reached a running system, what actually caused it, and the
check that stops it coming back.

**How to use this file.** Before shipping any change, read the *Classes*
section and ask whether the change belongs to one of them. After shipping,
add anything new. A bug that is fixed but not written down here will be
rediscovered, because the cause is almost never unique to the file it
appeared in.

Status key: `FIXED` verified by a test · `FIXED*` verified by hand only ·
`OPEN` known and unfixed.

---

## Classes — the patterns that keep producing bugs

These matter more than the individual entries. Nearly every bug below is an
instance of one of these, and checking a change against this list catches
more than re-reading the diff.

| # | Class | The question to ask before shipping |
|---|-------|-------------------------------------|
| **C1** | **Fixed at the write path, still broken at the render path** | New data is clean — but what about the rows already stored? Does the *display* code also need the fix? |
| **C2** | **Shipped a code path no test executes** | Does any test actually *call* this function, or does the suite only import it? |
| **C3** | **Edited against an anchor that was never verified** | Did I grep for this exact string before replacing it, or assume its shape? |
| **C4** | **The diagnostic hid the evidence** | Am I suppressing stderr or catching an exception on the very thing I am debugging? |
| **C5** | **Two consumers, one filename** | Does anything else read or write this path? Is one of them a source file and the other generated output? |
| **C6** | **A stale reference to something renamed or moved** | What else names this file, model, or field by its old name? |
| **C7** | **A cosmetic edit dropped functional code** | Did compressing or restyling this block silently delete a rule something depended on? |
| **C8** | **Recording is not recommending** | Does this treat every stored row as an endorsed action, when most were never flagged as actionable? |
| **C9** | **A threshold calibrated against the wrong reference** | What does *chance* score on this exact metric? Is the gate above what a good result can even produce? |
| **C10** | **Building something that already exists** | Did I grep for this capability before writing it? B33 was nearly a duplicate of a thorough engine already in the tree. |
| **C11** | **A default that froze at import** | Does this "read the environment" at call time, or did a dataclass/default argument capture it once when the module loaded? B54 deleted a live database through exactly this. |

---

## Open bugs

| ID | Bug | Class | Notes |
|----|-----|-------|-------|
| **B31** | **Home shows only what each model is working on**, with no route to the rest of the board or to assets grouped by readiness. | — | Partly addressed: model cards now carry badge, window and time-to-next-tier. Still wanted: a "Ready now" strip listing qualifying assets directly. |
| **B35** | **Per-asset pages do not state what to do** (buy / hold / sell), nor the plain-English reasons behind their wrong checks. | — | Requested. Needs the failure-mode breakdown, which the ledger already stores, rendered per asset. |

| ~~**B37**~~ | ~~No per-day P&L view.~~ Paper trading reports one cumulative curve; wanted is a daily view — that day's starting capital, trades, wins, losses — replacing Missed in the nav. | — | Agreed design: the DISPLAY resets daily, the ledger does not. Storage keeps every trade and every miss; only the page shows one day. |
| **B38** | **No suggested-picks view derived from paper-trading accuracy.** | — | Requested. Only meaningful for gated models, so it will be empty until more clear their bar. |
| **B32b** | **IPO windows still shown after they close** for cards whose coverage never carried a date. The 2-day age-out only fires once a publication date exists. | C1 | Needs an absolute floor: an undated listing card cannot outlive its first sighting by more than N days regardless. |
| **B33** | **No historical backtest.** Model accuracy is only measured forward, so a new model (e.g. thematic) must wait weeks before its record means anything. | — | Wanted: replay stored price history through a model and score it, kept clearly separate from live results. |

---

## Fixed

| ID | Bug | Class | Fix |
|----|-----|-------|-----|
| **B35** | **Per-asset pages gave no reason for their misses**, and still hardcoded "a coin flip would give 50%" after the tier gate was corrected — B34 surviving one level down. | C9, C6 | Pages now show the asset's own right/wrong counts, the model's measured null, and a plain-English failure breakdown ("went the other way" vs "right but too small to cover costs"). A first version computed right/wrong from the MODEL's rate times the ASSET's n, making the per-reason shares sum past 100%; now taken from the asset's own breakdown. FIXED |
| **B53** | **No fixed judging point.** A growing sample watched against a threshold is the multiple-comparisons problem: peek often enough and any bar is crossed by luck. | — | Each model now has a target sample fixed in advance, with a progress bar and wording that refuses to conclude before the sample is complete. FIXED |
| **B33** | **The walk-forward backtest engine existed but was unreachable** — only the screener called it, so a month of live checks was the only way to judge an idea. | — | Exposed as `python -m sigbot.runner backtest`: pooled across the board, decision-count weighted, never written to the ledger. Carries its three caveats every time (survivorship, fitting on the same history, replay-is-not-record). FIXED |
| **B58** | **THE BIG ONE — the resolver scored non-observations as misses.** When no new bar existed, it read back the same quote it opened on, so `exit_price == entry_price`. A zero move can never clear the cost bar, so each scored an automatic miss: **47% of the daily model's entire record, 38% of news**. The damage was not the lost rows — the measured **chance level is derived from the same rows**, so the null fell from 45.0% to 23.6%, and every tier, colour, gate and verdict in the system was computed against a number describing a resolver bug rather than a market. Corrected figures: daily 24.1% → **45.8%**; news 35.4% → **57.5%** with a floor of 48.3% against a 46.9% null — a real edge that was completely hidden. | C4, C9 | The resolver refuses to score a frozen price and leaves the row unresolved for the next run. `reset` unscores existing ones rather than deleting (the forecast was real, only the scoring was wrong). `diagnose` reports BAD DATA when frozen rows exceed 5%. FIXED |
| **B59** | **My own horizon analysis was measured from the contaminated data it was meant to diagnose.** It read `entry_price` snapshots and treated consecutive rows as consecutive sessions — several land within the same day. It reported a median 1-day move of 0.06% and "only 43% of windows can clear the cost bar", producing the diagnosis "the horizon leaves no room". Real daily closes for the same names: **1.57% median, 94% clearing**. It pointed at markets when the cause was B58. | C4 | `horizons` now fetches real market history. Verified against Shibui Finance: 14,860 real windows across 20 board names, 2 years. FIXED |
| **B55** | **A near-repeat of C9, one page over.** The ideas green threshold was set to 60% of the question set answered — but the set has seven entries and coverage answers at most four, so the achievable maximum is 57% and nothing could ever go green. Caught by checking the real distribution before shipping. | C9 | Green at 50% (a majority answered), with a test asserting the bar sits inside the achievable range. FIXED |
| **B56** | **Zero-width bars drew a visible stub**, so an asset with no checks looked like one with a little progress. The first fix guarded `pct > 0`, which a value of 0.4 passes — and then renders as "0%". | C3 | Every bar and meter routes through one helper that guards the **rounded** value and draws an empty track with a dash instead. A test asserts no `width:0%` anywhere on the page. FIXED |
| **B57** | **The board coloured by tier while sorting by tier, but the tiers said nothing about direction of travel.** An asset closer to removal than to qualifying looked identical to one improving. | — | Colour and sort now both derive from the two distances: red when drop exceeds ready, green above 90% ready, grey between. FIXED |
| **B54** | **A test of the reset command deleted the real ledger.** `type(SETTINGS)()` looks like it re-reads the environment, but a dataclass field default such as `os.environ.get("SIGBOT_DB", "shadow.db")` is evaluated **once at import**, so a monkeypatched path never reached the fresh instance and the DELETE ran against the live database. | C2, C3 | `reset-all` now refuses without `SIGBOT_CONFIRM_RESET=yes`, every reset snapshots to a `.bak` first, and the tests build an explicit settings object instead of relying on env. A test asserts the refusal. FIXED |
| **B51** | **Generated artifacts were tracked in git.** `app/data.json`, `app/public/index.html`, `app/sigbot-report.html` and `outbox.log` are rebuilt from the ledger on every run, on two machines. Tracking them asked git to merge two renderings of identical data — conflicting on every pull and breaking four consecutive ships, ending in a stuck rebase. | C5 | All four gitignored and untracked. The ledger stays tracked (it is the product); the renderings do not. The workflow rebuilds the page before deploying, so nothing depended on it being in the repo. FIXED |
| **B52** | **Contagion recorded only what it alerted.** One resolved check out of 17,583 firings: recording and alerting were the same decision, so the model could not learn because it refused to observe. | C8 | Two gates with different jobs — every triggered link is recorded and scored; only gated ones alert. FIXED |
| **B47** | **The drop bar was inverted.** A healthy upper bound of 0.60 against a 0.52 ceiling read as **85% of the way to removal**, so an asset could show "almost ready to trade" and "almost dropped" at once. Strong and doomed assets looked identical. | — | Closeness to removal now means what it says: comfortably above the ceiling is 0, at or below it is 100. FIXED |
| **B48** | **"BUY" was unreadable to someone already holding** — add, keep, or sell? The system does not know what anyone owns. | — | The call now states both readings: "BUY — or HOLD if already in", and no-evidence reads "NO ACTION", explicitly noting it is not a reason to sell either. FIXED |
| **B49** | **`npm run github` push rejected** when the scheduled tick landed between the pull and the push. | — | Push retries up to three times, rebasing onto whatever arrived. FIXED |
| **B50** | **The autostash conflict survived the reorder** — generated files (`data.json`, `outbox.log`, `paper.json`, `sigbot-report.html`) were still dirty at pull time, so git stashed our rendering and tried to merge it with the remote tick's rendering of the same data. | — | Generated files are discarded before the pull; they are rebuilt seconds later anyway. FIXED |
| **B45** | **`npm run github` conflicted on every single run.** The script published the page and *then* pulled, so git had to stash the freshly generated `app/public/index.html` and reapply it over the remote tick's own copy of the same file. Guaranteed conflict, a stash left behind each time, and eventually lost work. | — | Pull now precedes build, so the page is generated on top of what was just pulled. A test asserts that ordering. FIXED |
| **B46** | **Model pages listed the busiest 8 assets of 67.** A page showing a tenth of the board cannot answer "where should I look", which is the only question it is there for. | — | Every scored asset is exported, ordered by worst-case floor, each with a coloured tier dot and a bar showing how far its floor has travelled from chance to the trade gate. Plus an above/below-chance split banner counted against the measured null, not 50%. FIXED |
| **B40** | **The paper page rendered raw template text** — literal `{_e(model)}` and `{row["pnl"]:+,.0f}` appeared as words on the live site, because an F541 lint warning was silenced by dropping the `f` prefix from a concatenated literal that DID need interpolation. | C7 | Rewritten as one f-string. A guard now scans the rendered markup for any unrendered placeholder, so the whole class fails the suite. FIXED |
| **B41** | **The board printed its status counts twice**, the second block unstyled — the original `.legend` was left in place when the `board-status` pills were added. | C7 | Duplicate removed; a test asserts exactly one count block on the board page. FIXED |
| **B42** | **"Chance scores 50% … so that is the bar to beat, not 50%"** — the sentence contradicted itself whenever the fallback null was in use, undermining the one point it exists to make. | — | Three phrasings now: measured-and-different, measured-and-~50%, not-yet-measured. FIXED |
| **B43** | **A dated IPO card whose window had shut stayed on the page** — "Last day — closes today, 11 Sep" was live on 20 September. The undated filter could not see it (it HAD a date) and the write-path age-out only runs when the scan re-runs. | C1 | The render path now reads the date on the card and drops windows more than two days past. FIXED |
| **B44** | **The Ideas legend rendered as three run-together words** — it used a `.legend` class that was never styled in the override layer. | C7 | Reuses `board-status`, which is styled, rather than adding a second near-identical rule. FIXED |
| **B36** | **Follow-on moves had one resolved check in its entire life** — 6,661 links considered per run, 597 clearing the trigger, and essentially none recorded. Its direction gate demanded an **absolute 0.58** lower bound while the edge gate beside it asked only for `base + 3pp`; the two gates disagreed by ~16 points and the arbitrary one bound. | C9 | Gate is now `base_hit_rate + 6pp`, consistent with the tier fix. Honest footnote: this unlocks nothing today — the real links sit at 37-39% against a ~51% base, so the model genuinely has no edge in this universe. That is a result, not a bug. FIXED |
| **B32b** | **Undated IPO cards lingered forever** — the 2-day age-out only fired once a publication date existed, so a card whose coverage never gave dates stayed live indefinitely. | C1 | Dropped at the render path, with a visible count of what was hidden and why. No date is ever guessed. FIXED |
| **B39** | **Stored ideas rendered grey even after the colour fix** — the three-band fix applied at write time, so the 32 cards already in `opportunities.json` kept their old colour. | C1 | Ideas now sort by colour and carry a case-strength bar at the render path, so the page reflects the current rules immediately. FIXED |
| **B30** | **Board could not be sorted or filtered by colour** — a hundred rows in arbitrary order meant scrolling to find the two that qualified. | — | Rows now sort strongest-colour-first within each section, and each row carries two bars: distance to the trade bar and distance to removal. FIXED |
| **B34** | **THE BIG ONE — the skill gate was unreachable.** `hit` means "direction right AND move cleared trading costs", so a coin flip scores `0.50 x P(move cleared costs)` — measured at **30.4% for daily, 47.5% for crypto**, not 50%. The tiers demanded absolute 0.60/0.55/0.50. A genuinely strong model (55% raw direction) scores ~33% under this metric and could **never** pass, however good it got. "0 of 5 proven" read as patience; it was an unwinnable bar. | C9 | Tier rules now carry a **margin over the measured null** (+0.10/+0.05/+0.00 — the original standard, unchanged), and the ledger measures each model's null from its own resolved rows. News scanner immediately became the first model ever to clear a gate: 35.4% vs a 28.8% null. FIXED |
| **B29** | **Paper model replayed every resolved forecast as a trade** — ~9,320 positions nobody was ever told to take, so its P&L measured cost drag on noise. Reported −48.53%. | C8 | Replays only models that cleared their gate; reports the all-forecasts number beside it as a labelled noise benchmark. Gated: **+1.85%**. The gap — **+50.4 percentage points** — is the measured value of refusing to trade the ungated. FIXED |
| **B32a** | **Every Ideas card rendered grey.** Thesis colour had two bands, AMBER at ≥0.75 and GREY below, with GREEN unreachable for a thesis at all. Observed sourcing strengths run 40–70%, so every card came out grey and the colour carried no information. | C9 | Three bands — GREEN ≥0.75, AMBER ≥0.55, GREY below. FIXED |
| B01 | Scanned universe rows passed to the matcher as `SimpleNamespace`; matcher calls `asset.match_terms()` → whole news job crashed. | C2 | Convert rows to real `Asset` objects; test asserts a scanned row matches on its company name. FIXED |
| B02 | News feed sweep hung on slow feeds. | — | `FEED_TIMEOUT=10s`; 36/39 feeds alive. FIXED* |
| B03 | 42 notifications from one opportunity scan. | — | `MAX_PARTS=3` + digest capped at 6 cards. FIXED |
| B04 | `resolve()` priced crypto via Yahoo → fake −100%/+64% moves in the ledger. | C6 | Per-model price source: crypto via Binance, rest via Yahoo. FIXED |
| B05 | Pegged-coin filter leaked USD1 / RLUSD into the crypto universe. | — | `startswith`/`endswith` USD plus an explicit list. FIXED |
| B06 | IPO cards with relative dates ("allotment likely today") never dated; read against the real today they silently shifted forward forever. | — | Anchor relative words to the article's publication date. FIXED |
| B07 | A film premiere and an EV launch scored as NEW LISTINGS — trigger was the bare word "debut". | — | Require a market word (ipo, drhp, price band, gmp, allotment…). FIXED |
| B08 | Google News cards showed `"when:1d site:moneycontrol.com" - Google News` plus a 200-char redirect URL where an outlet name belonged. | C1 | Extract the real outlet at the write path **and** repair stored rows at the render path. FIXED |
| B09 | `doctor` reported "page not built yet" for a page built four minutes earlier — it checked a filename `publish` had stopped writing. | C6 | Point doctor at `app/public/index.html`. FIXED |
| B10 | `publish` crashed with `FileNotFoundError` — it deleted the working file, then called `stat()` on it. | — | Read the size from the surviving copy. FIXED |
| B11 | The deploy copy overwrote `app/index.html`, a template `build_standalone` reads. | C5 | Generated output lives in `app/public/` only. FIXED |
| B12 | `0Checked` ran together — the `.stats` CSS block was dropped when the override was compressed into the generator. | C7 | Block restored with tests on the rendered page. FIXED |
| B13 | Board render crashed: `{{}}` inside an f-string *expression* is a set containing a dict, not an empty dict. | — | Use `dict()`. FIXED |
| B14 | Every page rendered stacked on top of Home — `#home` sits before the pages, so a `~` sibling selector can never reach it. | — | `body:has(.page:target) #home{display:none}`. FIXED |
| B15 | `tidy_source` import inserted at an anchor that did not exist in `report.py` → `F821` at render. | C3 | Grep for the anchor first; import placed after `import html`. FIXED |
| B16 | `run_paper` called `load_settings()`, which does not exist. Suite stayed green because no test invoked the job; only the linter caught it. | C2 | Use `SETTINGS`; test executes the job the way the scheduler does. FIXED |
| B17 | `ModelView` dataclass: non-default field after defaulted ones → `TypeError` at import. | — | Defaults last. FIXED |
| B18 | CI exit 128 — workflow pushed to hardcoded `main`; the repo's branch is `master`. | C6 | `GITHUB_REF_NAME` everywhere. FIXED |
| B19 | CI: commit succeeded, then `git pull --rebase` refused over unstaged changes left by the jobs. | — | Per-file `git add -f`, then `git add -A`, then `--autostash`. FIXED |
| B20 | CI: packaged wrangler action cannot create a missing Pages project → opaque `npx exit 1`. | C4 | Plain script with create-if-missing. FIXED |
| B21 | CI: `2>/dev/null` on the create call silenced the very command being debugged. | C4 | Never suppress stderr on the command under investigation. FIXED |
| B22 | CI: Cloudflare token contained an invisible `U+2028` from the clipboard; the secret *looked* correct. | — | Re-copy with the provider's copy button; error now names the character. FIXED* |
| B23 | CI: `wrangler whoami` probe failed the build — it needs a permission the deliberately minimal token lacks. | C4 | Probe is `\|\| true`; the account id is asserted explicitly instead. FIXED |
| B24 | Google CSE returned a chain of errors (invalid key → invalid argument → project has no access) ending at a billing wall. | — | Abandoned; relative-date parsing covers most of the need for free. CLOSED |
| B25 | Window note printed twice on unknown-date cards — verdict and summary both carried it. | — | Summary carries it only when the window is actionable. FIXED |
| B26 | Crypto summary still said "scored in an hour / ninety-six bars" after the cadence moved to 3 hours. | C6 | Wording follows the schedule; test asserts it. FIXED |
| B27 | `daily` forecast crypto as well as stocks — two thin records per asset at two horizons. | — | Daily is stocks only. FIXED |
| B28 | Site fabricated a portfolio with holdings nobody held. | — | Guard test bans invented figures; the real paper portfolio must show a replay or say it has not run. FIXED |

---

## The rule this file exists to enforce

> A fix verified where the data is **written** is not verified where the data
> is **shown**. A function that imports cleanly is not a function that runs.
> An anchor you did not grep is an anchor that does not exist.

Three of the four most expensive bugs in this project were one of those.

And the most expensive of all was none of them. It was **C9**: a threshold
nobody checked against the metric it judged. The system spent its entire life
reporting "0 of 5 proven" against a bar that no model could have cleared. Ask
what chance scores, every time you write a number a model must beat.
