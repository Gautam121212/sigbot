"""Static report — three tabs, no JavaScript, plain English.

Every screen is real HTML and navigation is CSS `:target`, because iOS previews
HTML files with scripts disabled. A page that draws itself in JavaScript shows a
title bar and nothing else there.

## Language

The maths did not change; the wording did. "Wilson lower bound" is now "worst
case", "base rate" is "what a coin flip would give", "expectancy" is folded into
plain sentences. A term that needs a finance degree to read is a term that gets
skimmed, and a skimmed number is worse than no number.

## Three tabs

  Home     — the four models and how proven each one is
  Learned  — every prediction that came due, wins and misses together
  Missed   — only the misses, with how far off each one was

Wins and misses share the Learned feed on purpose. A feed showing only wins is a
highlight reel, and the reason for keeping a ledger is that it is not one.
"""
from __future__ import annotations

import html

from .plain_opportunities import tidy_source
import json
from pathlib import Path

from .charts import chart_url, indicator_note, tv_symbol
from .expectancy import size_position

ACCENT = {"teal": "#00d4aa", "purple": "#7c4dff", "red": "#ff6b6b", "green": "#00e676"}
# Green once MORE of the question set is answered than is still open — a
# majority known rather than unknown.
#
# This was briefly set to 60%, which nothing could ever reach: the question
# set has seven entries and coverage answers at most four of them, so the
# achievable maximum is 57%. That is C9 again — a threshold above what the
# metric can produce — the same bug as the original tier gate, one page over.
# Any bar here must be checked against the real distribution before it ships.
GREEN_IDEA_AT = 50.0

TIER_COLOR = {"TRADE": "#00e676", "CAUTION": "#ffd93d", "WATCH": "#00d4aa", "SILENT": "#8b8b9a"}
TIER_PLAIN = {
    "TRADE": "Proven enough to act on",
    "CAUTION": "Promising, small size only",
    "WATCH": "Worth watching, not acting",
    "SILENT": "Still collecting",
}

MECHANISM = {
    "stocks": ("It looks at every name it can reach, not a fixed list, and "
               "stays quiet on almost all of them. A green row means the "
               "reason it fired has worked in three separate stretches of "
               "history. A grey row means the reason looks promising but has "
               "not proved itself yet — those are traded at a third of the "
               "size, on purpose, so the system finds out rather than "
               "refusing to look.",
               "It reads price behaviour only. It cannot see why a price "
               "moved, so a company in real trouble looks the same to it as "
               "one that was sold off too hard."),

    "setups": ("It waits. Most days it says nothing at all, because the "
               "condition it looks for is rare. When a price has fallen far "
               "and fast enough that selling looks exhausted, it says so — "
               "and that condition was tested on ten years of history across "
               "three separate periods before it was allowed to speak.",
               "It cannot tell you WHY the price fell. A washout on bad news "
               "that keeps getting worse looks identical to one that is "
               "about to bounce."),

    "crypto15m": ("A guess at where a crypto pair goes over the next hour, from "
                  "fifteen-minute price and volume patterns. The count is how "
                  "often the direction was right.",
                  "whether the move was large enough to cover fees and spread. "
                  "Most fifteen-minute moves are not, which is why most "
                  "forecasts here are recorded rather than called"),
    "news": ("A story came out, we matched it to this company, and guessed which way "
             "the price would go. The count below is how often that guess was right.",
             "whether this story is already old news to everyone else. The count "
             "cannot tell a fresh story from the tenth rewrite of one"),
    "daily": ("A guess at tomorrow's direction, from price and volume patterns. The "
              "count is how often the direction was right.",
              "how far it moves. Being right 57% of the time on moves of 0.2% still "
              "loses money once you pay to trade"),
    "contagion": ("When one big company moves hard, we check whether this one follows "
                  "the next day. This is a count of what happened before, not a "
                  "forecast.",
                  "whether the link still works. These fade once people notice them, "
                  "so compare the early half against the recent half"),
    "opportunity": ("Investments and business ideas, rated on how good the available "
                    "evidence is rather than on how much they might make.",
                    "anything about profit. A good rating means the paperwork is real "
                    "and you could get your money out, not that it will go up"),
}

CSS = """
/* Design system: premium financial terminal, restrained. Accents live in
   icons, indicators, active nav and important numbers — the surfaces stay
   quiet. Elegance over effects, per the brief. */
:root{
  --bg:#0e1117; --bg2:#10141c;
  --panel:#151a24; --panel2:#1a2030; --hover:#1d2434;
  --line:rgba(148,163,196,.10); --line2:rgba(148,163,196,.16);
  --text:#e6e9f0; --dim:#9aa4b8; --faint:#68738c;
  --teal:#2dd4bf; --indigo:#818cf8; --amber:#fbbf24; --red:#f87171;
  --green:#34d399; --grey:#8b93a7; --accent:var(--teal);
  --r-lg:18px; --r-md:14px; --r-sm:10px;
}
*{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth}
body{overflow-wrap:anywhere;color:var(--text);
  background:var(--bg);
  background-image:radial-gradient(1100px 500px at 85% -10%,rgba(129,140,248,.06),transparent 60%),
                   radial-gradient(900px 420px at -10% 0%,rgba(45,212,191,.05),transparent 55%);
  font:15.5px/1.6 -apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",Roboto,Inter,sans-serif;
  -webkit-font-smoothing:antialiased;padding-bottom:88px}
.wrap{max-width:1080px;margin:0 auto;padding:22px 18px 48px}
.page{display:none;min-height:60vh}
.page:target{display:block}
#home{display:block}
body:has(.page:target) #home{display:none}
/* -------- header / nav -------- */
.top{display:flex;justify-content:space-between;align-items:baseline;
  padding:10px 0 14px;margin-bottom:18px;border-bottom:1px solid var(--line)}
.brand{font-size:21px;font-weight:700;letter-spacing:-.015em}
.brand em{font-style:normal;color:var(--indigo)}
.stamp{color:var(--faint);font-size:13px;font-variant-numeric:tabular-nums}
.dot{display:inline-block;width:6px;height:6px;border-radius:50%;
  background:var(--green);margin-right:7px;vertical-align:2px}
nav{position:fixed;left:0;right:0;bottom:0;z-index:9;display:flex;
  background:rgba(14,17,23,.92);backdrop-filter:blur(16px);
  border-top:1px solid var(--line2);
  padding:8px 2px calc(8px + env(safe-area-inset-bottom))}
nav a{flex:1;text-align:center;color:var(--faint);font-size:11px;
  font-weight:600;letter-spacing:.01em;padding:2px 0;border-radius:10px}
nav a b{display:block;font-size:17px;margin-bottom:2px;font-weight:400}
nav a:hover{color:var(--dim)}
/* -------- type hierarchy -------- */
h1{font-size:32px;font-weight:700;letter-spacing:-.02em;line-height:1.15}
h2{font-size:19px;font-weight:700;letter-spacing:-.01em;margin:26px 0 4px}
h3{font-size:13px;color:var(--dim);font-weight:600;letter-spacing:.02em}
.lead{color:var(--dim);margin:8px 0 4px}
.note{color:var(--faint);font-size:13px;padding:14px 0;line-height:1.55}
.what-sm{color:var(--faint);font-size:13px;margin:6px 0 8px}
a{color:inherit;text-decoration:none}
.back{display:inline-block;color:var(--indigo);font-weight:600;margin:12px 0 4px;font-size:14px}
/* -------- surfaces -------- */
.card{background:var(--panel);border:1px solid var(--line);
  border-radius:var(--r-lg);padding:18px 20px;margin:12px 0}
.card.call{background:linear-gradient(180deg,var(--panel2),var(--panel));
  border-color:var(--line2);padding:24px;border-radius:20px}
.card.stat{display:flex;flex-direction:column;background:var(--panel)}
.card.foot{display:flex;gap:16px;align-items:center;background:var(--bg2)}
.card.row{display:flex;gap:14px;align-items:center;padding:15px 18px;
  transition:background .12s,border-color .12s}
.card.row:hover{background:var(--hover);border-color:var(--line2)}
.hero{display:grid;gap:12px}
.statrow{display:flex;align-items:center;gap:10px;margin:4px 0}
.num{font-size:30px;font-weight:700;letter-spacing:-.02em;
  font-variant-numeric:tabular-nums}
.live{background:rgba(52,211,153,.12);color:var(--green);font-size:11.5px;
  font-weight:700;padding:3px 10px;border-radius:999px}
.sig{font-size:34px;font-weight:700;letter-spacing:-.02em}
.meter{height:6px;border-radius:99px;background:rgba(148,163,196,.12);
  overflow:hidden;margin:14px 0 10px}
.meter i{display:block;height:100%;border-radius:99px;background:var(--teal)}
.badge{display:inline-block;font-size:11.5px;font-weight:600;
  padding:3px 9px;border-radius:999px}
.av{width:42px;height:42px;border-radius:12px;display:flex;flex:none;
  align-items:center;justify-content:center;font-weight:700;font-size:16px;
  border:1px solid}
.chev{color:var(--faint);font-size:20px}
.rt{color:var(--dim);font-size:13px;white-space:nowrap;margin-left:auto;padding-left:10px}
details.horizon{margin:0 0 6px}
details.horizon>summary{cursor:pointer;list-style:none}
details.horizon>summary::-webkit-details-marker{display:none}
details.horizon>summary .chev{transition:transform .15s}
details.horizon[open]>summary .chev{transform:rotate(90deg)}
details.horizon>*:not(summary){margin-left:14px}
/* -------- board / lists -------- */
.tile{display:flex;gap:12px;align-items:flex-start;background:transparent;
  border:0;border-bottom:1px solid var(--line);border-radius:0;
  padding:13px 6px;margin:0;transition:background .12s}
.tile:hover{background:var(--hover)}
.tile b{min-width:104px;font-size:14.5px}
.tile .grow{flex:1;min-width:0}
.tile p{color:var(--faint);font-size:13px}
.tile p:first-child{color:var(--dim);font-weight:600;font-size:13.5px}
.pip{width:9px;height:9px;border-radius:50%;margin-top:6px;flex:none}
.tiles-grid{border:1px solid var(--line);border-radius:var(--r-md);
  padding:2px 10px;background:var(--panel)}
/* -------- desktop -------- */
@media(min-width:900px){
  body{padding-bottom:0;padding-top:58px;font-size:15px}
  .wrap{padding-top:26px}
  nav{top:0;bottom:auto;border-top:none;border-bottom:1px solid var(--line);
    justify-content:flex-start;gap:2px;padding:11px 24px;
    max-width:100%;align-items:center}
  nav:before{content:"Sigbot";font-weight:700;font-size:17px;
    margin-right:26px;color:var(--text)}
  nav a{flex:none;padding:6px 14px;font-size:13.5px;border-radius:8px}
  nav a b{display:none}
  nav a:hover{background:var(--hover);color:var(--text)}
  .hero{grid-template-columns:5fr 3fr}
  .grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px}
  .grid2 .card{margin:0}
  .tiles-grid{columns:2;column-gap:28px;padding:4px 18px}
  .tile{break-inside:avoid}
  h1{font-size:36px}
  .brand{display:none}
  .top{border-bottom:0;padding-bottom:0;margin-bottom:6px;justify-content:flex-end}
}

/* ===== premium terminal override — the visual layer, content untouched === */
:root{--bg:#0a0e13;--bg2:#0d1219;--panel:#111821;--panel2:#151e29;
  --panel3:#0f161f;--hover:#18222e;--line:rgba(164,181,204,.10);
  --line2:rgba(164,181,204,.18);--text:#edf2f7;--text2:#c8d1dc;
  --dim:#929eae;--faint:#647184;--teal:#48d8c0;--blue:#7da7ff;
  --indigo:#8b91ff;--green:#45d49a;--amber:#e6b85c;--red:#ef777d;
  --g:var(--green);--w:var(--text);
  --shadow:0 18px 55px rgba(0,0,0,.22);--shadow-soft:0 8px 30px rgba(0,0,0,.16)}
html{background:var(--bg)}
body{min-height:100vh;font-size:15px;line-height:1.65;
  background:radial-gradient(900px 500px at 82% -12%,rgba(92,125,190,.11),transparent 65%),
    radial-gradient(700px 420px at -10% 15%,rgba(51,137,131,.07),transparent 65%),
    linear-gradient(180deg,#0a0e13,#0b0f15 48%,#090d12)}
body::before{content:"";position:fixed;inset:0;pointer-events:none;z-index:-1;
  background-image:linear-gradient(rgba(255,255,255,.018) 1px,transparent 1px),
    linear-gradient(90deg,rgba(255,255,255,.018) 1px,transparent 1px);
  background-size:72px 72px;
  mask-image:linear-gradient(to bottom,rgba(0,0,0,.35),transparent 65%)}
.wrap{width:min(1320px,calc(100% - 48px));max-width:1320px;padding:32px 0 72px}
h1{font-size:clamp(34px,4vw,52px);line-height:1.05;letter-spacing:-.035em;font-weight:750}
h2{margin:42px 0 7px;font-size:20px;letter-spacing:-.018em}
h4{margin:34px 0 10px;font-size:13px;text-transform:uppercase;
  letter-spacing:.07em;font-weight:750}
.lead{max-width:850px;color:var(--text2);font-size:16px;line-height:1.7}
.note{max-width:900px;font-size:12.5px}
.eyebrow{display:flex;align-items:center;gap:9px;margin-bottom:18px;
  color:var(--faint);font-size:10px;font-weight:750;letter-spacing:.12em;
  text-transform:uppercase}
.sechead{display:flex;align-items:end;justify-content:space-between;gap:20px;
  margin:42px 0 10px}
.seccount{color:var(--faint);font-size:11px;text-transform:uppercase;
  letter-spacing:.08em}
.brand em{color:var(--teal);background:none;-webkit-background-clip:unset;
  background-clip:unset}
.dot{box-shadow:0 0 0 3px rgba(69,212,154,.08)}
nav{background:rgba(8,12,17,.88);border-color:var(--line2);
  backdrop-filter:blur(22px);box-shadow:0 8px 30px rgba(0,0,0,.15)}
nav a span{display:block;font-size:11px}
.card{background:linear-gradient(145deg,rgba(255,255,255,.025),rgba(255,255,255,.008)),var(--panel);
  box-shadow:var(--shadow-soft)}
.card.call{padding:30px 32px;border-radius:24px;border-color:var(--line2);
  box-shadow:var(--shadow);
  background:radial-gradient(700px 250px at 100% 0%,rgba(83,112,165,.10),transparent 70%),
    linear-gradient(145deg,#151d28,#10161e)}
.hero{grid-template-columns:minmax(0,1.55fr) minmax(300px,.75fr);gap:16px}
.hero .call{min-height:285px;display:flex;flex-direction:column;justify-content:center}
.hero .stat{min-height:285px;justify-content:center;
  background:linear-gradient(150deg,#121a24,#0e141c)}
.hero .stat::before{content:"TODAY";display:block;margin-bottom:28px;
  color:var(--faint);font-size:10px;font-weight:750;letter-spacing:.12em}
.hero .stat .num{font-size:clamp(42px,5vw,62px);line-height:1;letter-spacing:-.045em}
.sig{font-size:42px}
.meter{height:7px;margin:22px 0 12px;background:rgba(150,165,185,.09)}
.meter i{background:linear-gradient(90deg,var(--teal),#79d9c8);
  box-shadow:0 0 12px rgba(72,216,192,.12)}
.grid2{gap:14px}
.card.row{min-height:105px;padding:19px 20px;border-radius:14px}
.card.row:hover{transform:translateY(-2px);box-shadow:0 14px 35px rgba(0,0,0,.18)}
.card.row .grow p{color:var(--text2)}
.av{background:#17212c!important;border:1px solid var(--line2)!important;
  color:var(--teal)!important;font-size:14px}
.chev{transition:color .18s,transform .18s}
.card.row:hover .chev{color:var(--text);transform:translateX(3px)}
.badge{margin-top:7px;background:rgba(255,255,255,.055)!important;
  color:var(--dim)!important;border:1px solid rgba(255,255,255,.07);
  font-size:10.5px}
.live{background:rgba(69,212,154,.09);border:1px solid rgba(69,212,154,.16)}
.card.foot{margin-top:24px;padding:26px 28px;border-color:var(--line2);
  align-items:flex-start;
  background:linear-gradient(135deg,rgba(72,216,192,.035),rgba(125,167,255,.025)),var(--panel3)}
.stats{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));
  gap:12px;margin:14px 0 26px}
.stats .stat{min-height:105px;display:flex;flex-direction:column;
  justify-content:center;padding:20px;background:var(--panel);
  border:1px solid var(--line);border-radius:var(--r-md);
  box-shadow:var(--shadow-soft)}
.stats .stat b{display:block;margin-bottom:4px;color:var(--text);
  font-size:28px;line-height:1;letter-spacing:-.03em;
  font-variant-numeric:tabular-nums}
.stats .stat span{color:var(--faint);font-size:11px;
  text-transform:uppercase;letter-spacing:.08em}
@media(max-width:420px){.stats{gap:7px}
  .stats .stat{min-height:90px;padding:13px 10px}
  .stats .stat b{font-size:20px}
  .card.row{padding:13px 14px;gap:10px}
  .rt{font-size:11px;padding-left:6px}
  .num{font-size:26px}
  h1{font-size:24px}
  .lead{font-size:14.5px}}
/* iPad / tablet portrait: keep cards comfortable, not stretched */
@media(min-width:600px) and (max-width:900px){
  .wrap{padding:24px 20px 56px}
  .card.row{padding:16px 20px}}
.dualbar{display:flex;align-items:center;gap:8px;margin-top:5px;
  font-size:10px;color:var(--faint);letter-spacing:.03em}
.dualbar span:first-child{min-width:34px;text-transform:uppercase}
.dualbar span:last-child{min-width:30px;text-align:right;
  font-variant-numeric:tabular-nums}
.dualbar i{flex:1;height:4px;border-radius:99px;
  background:rgba(148,163,196,.14);overflow:hidden;display:block}
.dualbar i b{display:block;height:100%;border-radius:99px}
.hbadge{display:inline-block;margin-top:8px;padding:3px 10px;
  border:1px solid var(--line);border-radius:999px;font-size:11px;
  font-weight:600;letter-spacing:.02em}
.board-status{display:flex;flex-wrap:wrap;gap:8px;margin:18px 0 16px}
.board-status span{display:inline-flex;align-items:center;gap:8px;
  padding:8px 11px;background:rgba(255,255,255,.035);
  border:1px solid var(--line);border-radius:999px;color:var(--dim);font-size:11px}
.board-status .pip{margin:0;width:6px;height:6px}
.tiles-grid{padding:7px 18px;border-radius:18px;box-shadow:var(--shadow-soft);
  background:linear-gradient(145deg,rgba(255,255,255,.018),transparent),var(--panel)}
.tile{min-height:72px;padding:16px 8px;align-items:center;
  transition:background .16s,padding .16s}
.tile:last-child{border-bottom:0}
.tile:hover{padding-left:13px;
  background:linear-gradient(90deg,rgba(72,216,192,.035),transparent)}
.tile b{min-width:120px;font-size:13px}
.tile p:first-child{color:var(--text2)!important;font-size:13px}
.pip{width:7px;height:7px;box-shadow:0 0 0 3px rgba(255,255,255,.025)}
#ideas > .wrap > .note{max-width:850px;padding:17px 19px;border-radius:13px;
  background:rgba(125,167,255,.035);border:1px solid rgba(125,167,255,.10)}
#learned .card.row:has(.dot[style*="00e676"]),
#learned .card.row:has(.pip[style*="00e676"]){
  border-left:2px solid rgba(69,212,154,.55)}
#learned .card.row:has(.dot[style*="ff6b6b"]),
#learned .card.row:has(.pip[style*="ff6b6b"]){
  border-left:2px solid rgba(239,119,125,.45)}
#missed > .wrap::before{content:"FAILURE PATTERNS";display:block;
  margin-bottom:9px;color:var(--red);font-size:10px;font-weight:750;
  letter-spacing:.13em;opacity:.75}
#missed .card.row{background:linear-gradient(90deg,rgba(239,119,125,.025),transparent 70%),var(--panel)}
dl{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:0;margin:0}
dt,dd{padding:12px 0;border-bottom:1px solid var(--line)}
dt{color:var(--dim);font-size:13px}
dd{color:var(--text);font-size:14px;font-weight:650;text-align:right;
  font-variant-numeric:tabular-nums}
dt:last-of-type,dd:last-of-type{border-bottom:0}
ul{padding-left:20px}
li{margin:9px 0;color:var(--text2)}
li::marker{color:var(--faint)}
.back{display:inline-flex;align-items:center;margin:4px 0 18px;
  padding:7px 11px;color:var(--dim);background:rgba(255,255,255,.025);
  border:1px solid var(--line);border-radius:9px;font-size:12px}
.back:hover{color:var(--text);background:rgba(255,255,255,.05);
  border-color:var(--line2)}
@media(min-width:900px){
  body{padding-top:62px}
  nav{height:62px;padding:0 34px;gap:3px}
  nav a{position:relative;height:100%;display:flex;align-items:center;
    padding:0 17px;border-radius:0;font-size:13px;font-weight:650}
  nav a::after{content:"";position:absolute;left:17px;right:17px;bottom:0;
    height:2px;background:var(--teal);transform:scaleX(0);
    transform-origin:center;transition:transform .2s}
  nav a:hover{background:transparent}
  nav a:hover::after{transform:scaleX(.7)}
  nav a b{display:none}
  nav a span{font-size:13px}
  .tiles-grid{columns:2;column-gap:40px}}
@media(max-width:899px){
  .wrap{width:min(calc(100% - 28px),720px);padding-top:20px;
    padding-bottom:105px}
  .hero{grid-template-columns:1fr}
  .hero .call,.hero .stat{min-height:auto}
  nav{min-height:70px}
  nav a b{font-size:18px;line-height:1.2;font-weight:400}
  nav a:hover b{color:var(--teal)}}
@media(prefers-reduced-motion:reduce){*,*::before,*::after{
  scroll-behavior:auto!important;transition:none!important}}
"""


def _e(x) -> str:
    return html.escape(str(x))


def _pct(v) -> str:
    return "—" if v is None else f"{v * 100:.0f}%"


def _signed(v) -> str:
    return "—" if v is None else f"{v * 100:+.1f}%"


def _plain_risk_note(n: int, note: str) -> str:
    """Translate the sizing note for a reader who does not know the terms.

    `expectancy.size_position` is deliberately precise — it says "Wilson lower
    bound" and "quarter-Kelly" because those are the actual methods. That
    precision belongs in the code, not on a phone screen at 8am, so the wording
    is swapped here rather than watered down at the source.
    """
    if "not an estimate" in note:
        return (f"Only {n} checks so far. That is not enough to tell a real edge from "
                "luck, so the answer is to risk nothing and keep watching.")
    if "does not clear" in note:
        return ("Even taking the worst case, this is no better than a coin flip. "
                "Risk nothing until that changes.")
    if "clears" in note:
        return ("The worst case still beats a coin flip, so there is something here. "
                "The 2% ceiling holds no matter how good it looks.")
    return note


# How long each model's signal stays actionable, in days. From the horizons
# the models actually use.
SIGNAL_WINDOW_DAYS = {
    "crypto15m": 1, "news": 1, "daily": 1, "contagion": 5, "stocks": 20,
    "opportunity": 90,
}


def _prediction_time_labels(a: dict) -> str:
    """The three time labels for a prediction (item 7): when it was made, the
    predicted move, and when its result is due."""
    made = a.get("made_at", "")
    result = a.get("result_at", "")
    move = a.get("predicted_move", "")
    if not (made or result or move):
        return ""
    rows = []
    if made:
        rows.append(f"<dt>Prediction made on</dt><dd>{_e(made)} UTC</dd>")
    if move:
        rows.append(f"<dt>Predicted move</dt><dd>{_e(move)}</dd>")
    if result:
        rows.append(f"<dt>Result time</dt><dd>{_e(result)} UTC</dd>")
    return f'<div class="card"><dl>{"".join(rows)}</dl></div>'


def _signal_window(model_id: str, generated_at: str) -> str:
    """Plain-language dates: when to act by, when the window closes, and a
    warning not to chase a move that has already happened."""
    from datetime import datetime, timedelta, timezone
    days = SIGNAL_WINDOW_DAYS.get(model_id, 1)
    try:
        start = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        start = datetime.now(timezone.utc)
    end = start + timedelta(days=days)
    unit = "same day" if days <= 1 else f"{days} days"
    horizon = ("intra-day" if days <= 1 else "short-term" if days <= 15 else "long-term")
    return (f'<div class="card"><h4>When to act</h4>'
            f'<dl><dt>Horizon</dt><dd>{horizon} (holds about {unit})</dd>'
            f'<dt>Act from</dt><dd>{start:%d %b %Y}</dd>'
            f'<dt>Act BY (window closes)</dt><dd>{end:%d %b %Y}</dd></dl>'
            f'<p style="color:#e0a030;margin-top:8px">After {end:%d %b %Y} this '
            f'signal expires and is removed from the list — do not enter past that '
            f'date. Do not chase: if the move has already happened, skip it.</p></div>')


def _call(model: dict, a: dict) -> tuple[str, str, str]:
    """What the record permits, stated so it cannot be read two ways.

    "BUY" on a green asset left it ambiguous whether someone already holding
    should add, hold or sell. The system does not know what anyone owns, so
    the honest wording covers both readings explicitly rather than picking one
    and being wrong half the time.
    """
    tier, n = a.get("tier", "SILENT"), a.get("resolved", 0)
    side = str(a.get("side") or "").upper()
    direction = "BUY" if side != "SELL" else "SELL"
    opposite = "sell" if direction == "BUY" else "buy back"

    if tier in ("TRADE", "CAUTION"):
        return (f"{direction} — or HOLD if already in",
                TIER_COLOR[tier],
                f"the record beats chance across {n:,} checks; if you already "
                f"hold this, the record says keep it, not {opposite}")
    if tier == "WATCH":
        return ("NO ACTION — watch only", TIER_COLOR["WATCH"],
                "there is something here, but not enough to open or close a "
                "position on")
    return ("NO ACTION — not enough evidence", TIER_COLOR["SILENT"],
            f"only {n:,} checks so far; nothing here justifies buying, and "
            "nothing here justifies selling either")


def _detail(model: dict, a: dict) -> str:
    sym, n = a["symbol"], a.get("resolved", 0)
    sig, col, reason = _call(model, a)
    rate, floor = model.get("hit_rate"), model.get("lower_bound")
    mech, blind = MECHANISM.get(model["id"], ("", ""))
    # Against the metric's own null, not 0.50. The asset page was still
    # hardcoding a coin flip at 50% after the tier gate was corrected — the
    # same bug, surviving one level down.
    null = a.get("null_rate") or model.get("null_rate") or 0.50
    edge = (floor - null) if floor is not None else None
    # From the asset's OWN failure breakdown, not the model's hit rate times
    # this asset's n. Mixing those made the per-reason percentages sum past
    # 100% — the counts described one asset and the total described another.
    failures = a.get("failures") or {}
    if failures:
        right = int(failures.get("win", 0))
        wrong = sum(v for k, v in failures.items() if k != "win")
        # The asset's OWN rate from its own wins/checks — NOT the model-wide
        # rate. Showing the model's 56% next to a symbol with 1 check was the
        # "1 check but 56%" confusion: two different scopes on one line.
        rate = (right / n) if n else 0.0
    else:
        right = int(round((rate or 0) * n))
        wrong = max(n - right, 0)
    side_label = (a.get("side") or "call").lower()
    shortcomings = _shortcomings(failures, wrong)
    sizing = size_position(n, int(round((rate or 0) * n)), target_r=1.0) if n else None
    risk = sizing.recommended_risk_pct if sizing else 0.0
    risk_note = (_plain_risk_note(n, sizing.note) if sizing
                 else "Nothing has been checked yet, so there is nothing to size.")

    return f"""
<div class="page" id="d-{_e(model['id'])}-{_e(sym)}"><div class="wrap">
  <a class="back" href="#m-{_e(model['id'])}">&lsaquo; {_e(model['name'])}</a>
  <div class="card call"><div class="sig" style="color:{col}">{sig}</div>
    <div class="sub">{_e(sym)} &middot; {_e(model['name'])}</div>
    {f'<p class="what">{_e(a["description"])}</p>' if a.get("description") else ''}</div>
  <p class="lead">{_e(reason.capitalize())}.</p>
  {_signal_window(model['id'], model.get('generated_at', '')) if sig.startswith(('BUY','SELL')) else ''}
  {_prediction_time_labels(a)}

  <h4>Where the number comes from</h4>
  <div class="card"><dl>
    <dt>Times checked</dt><dd>{n:,}</dd>
    <dt>Right</dt><dd>{int(round(rate * n)):,} of {n:,} ({_pct(rate)})</dd>
    <dt>Wrong</dt><dd>{wrong:,} of {n:,}</dd>
    <dt>Worst case on a {_e(side_label)}</dt><dd style="color:{col}">{_pct(floor)}</dd>
    <dt>A coin flip would give</dt><dd>{_pct(null)}</dd>
    <dt>Better than a coin by</dt>
    <dd style="color:{'var(--green)' if edge and edge > 0 else 'var(--red)'}">
      {'—' if edge is None else f'{edge * 100:+.0f} points'}</dd>
  </dl>
  {('<p style="color:var(--red)">Negative means it has done WORSE than a coin'
    ' flip so far — it is losing, not winning. A coin flip is 50%; this is below'
    ' it.</p>') if (edge is not None and edge < 0) else ''}
  {_meter(min(100, (floor or 0) * 100), col)}
  <p>Use the worst case, not the headline number. With {n:,} checks behind it,
  that is what the record actually supports — the higher figure is the luckiest
  reading of the same data. Few checks means a low worst case even when the
  headline looks good. That is the honest answer, not a broken one.</p></div>

  <h4>Why the wrong ones were wrong</h4>
  <div class="card">{shortcomings}</div>

  <h4>What we are actually measuring</h4>
  <div class="card"><p>{_e(mech)}</p></div>

  <h4>What this will not tell you</h4>
  <div class="card"><ul>
    <li>Not {_e(blind)}.</li>
    <li>Not how big the move will be. We count which way it went, not how far.</li>
    <li>Not whether it still works today. Patterns fade once people spot them.</li>
  </ul></div>

  <h4>What to do about it</h4>
  <div class="card"><dl><dt>Risk per position</dt>
    <dd style="color:{'var(--green)' if risk > 0 else 'var(--g)'}">{risk:.2f}%</dd></dl>
    <p style="margin-top:10px">{_e(risk_note)}</p>
    <p style="margin-top:10px">This is deliberately small: a quarter of the
    largest bet the maths allows, worked out from the worst case rather than the
    headline number, and never above 2% of your money. Sizing off the headline is
    how accounts get wiped out while the idea itself was still fine.</p></div>
</div></div>"""


def _model_page(m: dict) -> str:
    col = ACCENT.get(m["accent"], "#00d4aa")
    tc = TIER_COLOR.get(m["tier"], "#8b8b9a")
    # A coloured dot per asset, so the state is readable without opening
    # anything, and a bar showing how far its floor has travelled from chance
    # to the trade gate — which is the question "where do I spend attention"
    # in its only answerable form.
    _row_fn: object = None
    if m["id"] == "stocks":
        rows = _scan_rows(m)
    elif m["id"] == "opportunity" and m.get("sector_cards"):
        rows = _sector_rows(m)
    else:
        # Group crypto / news / follow-on / daily into the three horizon rows,
        # same as stocks. Each row expands to its assets.
        def _one_row(a: dict, _mid=m["id"], _col=col) -> str:
            tcol = TIER_COLOR.get(a.get("tier", "SILENT"), "#8b8b9a")
            return f"""
    <a href="#d-{_e(_mid)}-{_e(a['symbol'])}"><div class="card row">
      <span class="pip" style="background:{tcol};margin-top:0"></span>
      <div class="av" style="background:{_col}1f;border-color:{_col}59;color:{_col}">
        {_e(a['symbol'][:3])}</div>
      <div class="grow"><h3>{_e(a['symbol'])}</h3>
        {f'<p class="what-sm">{_e(a["description"])}</p>' if a.get("description") else ''}
        <p>{_e(a['detail'])}</p>
        {_bar("ready to act", a.get("to_trade", 0), tcol)}</div>
      <span class="chev">&rsaquo;</span></div></a>"""
        rows = _horizon_groups(m, _one_row) or "".join(_one_row(a) for a in m["alerts"])
        _row_fn = _one_row
    if m["id"] == "stocks":
        _row_fn = _one_scan_row
    elif m["id"] == "opportunity":
        _row_fn = None
    return f"""
<div class="page" id="m-{_e(m['id'])}"><div class="wrap">
  <a class="back" href="#home">&lsaquo; Home</a>
  <div class="card"><h1>{_e(m['name'])}</h1>
    <p style="margin-bottom:10px">{_e(m['subtitle'])}</p>
    <span class="hbadge" style="color:{_e(m.get('badge_colour', 'var(--faint)'))};
      border-color:{_e(m.get('badge_colour', 'var(--line)'))}33">
      {_e(m.get('badge', ''))} · {_e(m.get('window', ''))}</span>
    <p class="what-sm" style="margin-top:10px">{_e(m.get('intake', ''))}.</p>
    <p class="what-sm" style="margin-top:6px">{m.get('ready_count', 0)} of 5 names
    ready to trade — the model is proven once 5 have a clear, tradeable action.</p>
    {_bar("proven", m.get("proven_progress", 0), "var(--green)")}
    <p class="what-sm">{_e((f"{m.get('made', 0):,} forecast(s) recorded, waiting to be scored. "
                            if m.get('made') and not m.get('resolved') else "")
                           + (m.get('last_run') or
                              "No run recorded yet — if this persists a day, "
                              "the job is not running, which is a fault."))}</p></div>
  <div class="stats">
    <div class="stat"><b>{m['resolved']:,}</b><span>Checked</span></div>
    <div class="stat"><b>{_pct(m.get('hit_rate'))}</b><span>Right</span></div>
    <div class="stat"><b style="color:{tc}">{_pct(m.get('lower_bound'))}</b><span>Worst case</span></div>
  </div>
  <h4>What would prove this wrong</h4>
  <div class="card"><p>{_e(m.get('falsifier', ''))}</p></div>
  {_asset_split(m)}
  <h2>{"What fired" if m["id"] == "stocks" else "What it is watching"} ({len(m["alerts"])})</h2>
  {_scan_note(m)}
  {rows or '<div class="card"><p>Nothing has been checked for this one yet. It stays quiet until it has something to show.</p></div>'}
  <p class="note">Tap any row for the full reasoning.</p>
</div></div>
{"".join(_detail(m, a) for a in m["alerts"])}
{_horizon_pages(m, _row_fn) if _row_fn else ""}"""


def _feed_card(e: dict, page: str, colour: str) -> str:
    times = f"&times;{e['count']}" if e.get("count", 1) > 1 else ""
    return f"""
  <a href="#{page}-{e['id']}"><div class="card row">
    <span class="dot" style="background:{colour}"></span>
    <div class="grow"><h3>{_e(e['symbol'])} &middot; {_e(e['model_name'])}
      <span class="times">{times}</span></h3><p>{_e(e['brief'])}</p></div>
    <span class="chev">&rsaquo;</span></div></a>"""


def _occurrences(e: dict) -> str:
    rows = e.get("occurrences") or []
    if len(rows) < 2:
        return ""
    listed = "".join(
        f"<dt>{_e(o['when'])}</dt><dd>{_signed(o.get('moved_pct'))}</dd>" for o in rows)
    more = (f"<p style=\"margin-top:10px\">Showing {len(rows)} of {e['count']}.</p>"
            if e["count"] > len(rows) else "")
    return f"""
  <h4>Each time it happened</h4>
  <div class="card"><dl>{listed}</dl>{more}</div>"""


def _learned_detail(e: dict) -> str:
    colour = "#00e676" if e["hit"] else "#ff6b6b"
    times = "once" if e["count"] == 1 else f"{e['count']} times"
    return f"""
<div class="page" id="learned-{e['id']}"><div class="wrap">
  <a class="back" href="#learned">&lsaquo; Top suggestions</a>
  <div class="card call"><div class="sig" style="color:{colour};font-size:22px">
    {_e(e['headline'])}</div>
    <div class="sub">{_e(e['symbol'])} &middot; {_e(e['model_name'])} &middot; {times}</div>
    {f'<p class="what">{_e(e["description"])}</p>' if e.get("description") else ''}</div>
  <h4>What happened</h4>
  <div class="card"><dl>
    <dt>We expected it to go</dt><dd>{_e(e['expected_side'])}</dd>
    <dt>Times this repeated</dt><dd>{e['count']}</dd>
    <dt>Average move</dt><dd>{_signed(e.get('avg_move_pct'))}</dd>
    <dt>We had guessed about</dt><dd>{_signed(e.get('avg_expected_pct'))}</dd>
    <dt>Between</dt><dd>{_e(e['first_seen'])} &ndash; {_e(e['last_seen'])}</dd>
  </dl></div>
  <h4>What that means</h4>
  <div class="card"><p>{_e(e['detail'])}</p></div>
  {_occurrences(e)}
  <h4>What it changes</h4>
  <div class="card"><p>One check on its own changes almost nothing — it moves the
  running count by a fraction. A result that repeats {times} is different: that
  is a pattern, and it is what the Home tab is built from. This page exists so
  you can see the raw material rather than only the summary.</p></div>
</div></div>"""


def _missed_detail(e: dict) -> str:
    times = "once" if e["count"] == 1 else f"{e['count']} times"
    return f"""
<div class="page" id="missed-{e['id']}"><div class="wrap">
  <a class="back" href="#missed">&lsaquo; Where it missed</a>
  <div class="card call"><div class="sig" style="color:#ff6b6b;font-size:22px">
    {_e(e['headline'])}</div>
    <div class="sub">{_e(e['symbol'])} &middot; {_e(e['model_name'])} &middot; {times}</div>
    {f'<p class="what">{_e(e["description"])}</p>' if e.get("description") else ''}</div>
  <h4>How far off</h4>
  <div class="card"><dl>
    <dt>We expected it to go</dt><dd>{_e(e['expected_side'])}</dd>
    <dt>Times this repeated</dt><dd>{e['count']}</dd>
    <dt>We had guessed about</dt><dd>{_signed(e.get('avg_expected_pct'))}</dd>
    <dt>Average actual move</dt><dd>{_signed(e.get('avg_move_pct'))}</dd>
    <dt>Average against us</dt><dd style="color:#ff6b6b">{_signed(e.get('avg_against_pct'))}</dd>
    <dt>Worst single one</dt><dd style="color:#ff6b6b">{_signed(e.get('worst_pct'))}</dd>
    <dt>Between</dt><dd>{_e(e['first_seen'])} &ndash; {_e(e['last_seen'])}</dd>
  </dl></div>
  {_occurrences(e)}
  <h4>Why it went wrong</h4>
  <div class="card"><p>{_e(e['detail'])}</p></div>
  <h4>What we do about it</h4>
  <div class="card"><p>A single miss means nothing — an idea that is right two
  times in three is wrong the other time, and reacting to each one is chasing
  noise. This one repeated {times}, which is the part worth reading.
  If "went the other way" dominates, the idea has no edge and gets dropped. If
  "right, but too small" dominates, the direction works and the target is too
  tight to cover costs. That is the whole reason for sorting misses by cause.</p>
  </div>
</div></div>"""


def build_report(data: dict) -> str:
    h = data["headline"]
    proven, total = h["models_alertable"], h["models_total"]
    learning = data.get("learning", [])
    failures = data.get("failures", [])

    cards = "".join(f"""
    <a href="#m-{_e(m['id'])}"><div class="card row">
      <div class="av" style="background:{ACCENT.get(m['accent'], '#00d4aa')}1f;
        border-color:{ACCENT.get(m['accent'], '#00d4aa')}59;
        color:{ACCENT.get(m['accent'], '#00d4aa')}">{_e(m['name'][0])}</div>
      <div class="grow"><h3>{_e(m['name'])}</h3><p>{_e(m['subtitle'])}</p>
        <p class="what-sm" style="margin:8px 0 2px">{m.get('ready_count', 0)} of 5
        ready — how close to placing real-money trades.</p>
        {_bar("to real money", m.get("proven_progress", 0), "var(--green)")}</div>
      <span class="chev">&rsaquo;</span></div></a>""" for m in data["models"])

    empty = ('<div class="card"><p>Nothing checked yet. Come back once the '
             'collector has run for a few days.</p></div>')

    b = data.get("board", {})

    def _tile(a):
        """One board row, coloured by the thing that actually matters.

        The tier colour said what an asset IS. What you need to know is where
        it is HEADING, and the two distances already say that:

          red   — closer to being dropped than to qualifying. A danger zone.
          green — 90% or more of the way to the trade bar.
          grey  — making progress, not there yet.

        A bar at zero draws nothing at all. The old one rendered a stub in the
        middle of an empty track, which read as "halfway" on an asset with no
        checks — the opposite of the truth.
        """
        ready, drop = _board_progress(a)
        colour, state = _board_state(ready, drop)

        def bar(label, pct, shade):
            if round(pct) <= 0:
                return (f'<div class="dualbar dualbar-empty"><span>{label}</span>'
                        f'<span>not yet</span></div>')
            return (f'<div class="dualbar"><span>{label}</span>'
                    f'<i><b style="width:{pct:.0f}%;background:{shade}"></b></i>'
                    f'<span>{pct:.0f}%</span></div>')

        return f"""
  <div class="tile"><span class="pip" style="background:{colour}"></span>
    <b>{_e(a['symbol'])}</b>
    <div class="grow"><p style="color:{colour}">{_e(state)}</p>
      <p>{_e(a['reason'])}</p>
      {bar("ready", ready, "var(--green)")}
      {bar("drop", drop, "var(--red)")}</div></div>"""

    # Stocks and crypto are different games — different hours, different costs,
    # different volatility. One undivided wall of a hundred names made the
    # board read as noise; two sections make it read as two answers.
    # Sorted by colour, strongest first: a hundred rows in arbitrary order
    # meant scrolling to find the two that qualified.
    # Sorted by the SAME rule that colours the dot. Ordering by the old tier
    # while colouring by progress would put a red row above a green one and
    # make the page contradict itself.
    def _sort_key(a):
        ready, drop = _board_progress(a)
        _colour, state = _board_state(ready, drop)
        rank = {"Close — nearly ready": 0, "Building": 1, "Danger — losing ground": 2}
        return (rank.get(state, 9), -ready, drop, a.get("symbol", ""))

    ordered = sorted(b.get("assets", []), key=_sort_key)
    stocks = [a for a in ordered if a.get("kind") != "crypto"]
    coins = [a for a in ordered if a.get("kind") == "crypto"]
    tiles = ""
    if stocks:
        tiles += (f'<h3 style="margin:16px 0 6px">Stocks ({len(stocks)})</h3>'
                  f'<div class="tiles-grid">'
                  + "".join(_tile(a) for a in stocks) + "</div>")
    if coins:
        tiles += (f'<h3 style="margin:22px 0 6px">Crypto ({len(coins)})</h3>'
                  f'<div class="tiles-grid">'
                  + "".join(_tile(a) for a in coins) + "</div>")

    # Charts show every asset, measured or not. A price chart needs no record
    # to be worth looking at, and hiding an asset from Charts because its
    # forecasts have not resolved yet would remove the one view that works
    # from day one.
    every_asset = list(b.get("assets", [])) + list(b.get("waiting", []))

    drawn = {c["symbol"] for c in data.get("charts", [])}
    charts = "".join(f"""
  <a href="{('#c-' + a['symbol'].replace('.', '_').replace('-', '_'))
            if a['symbol'] in drawn
            else _e(chart_url(a['symbol'], a.get('kind', 'equity')))}"
     {'' if a['symbol'] in drawn else 'target="_blank" rel="noopener"'}><div class="tile">
    <span class="pip" style="background:{_e(a['colour'])}"></span>
    <b>{_e(a['symbol'])}</b>
    <div class="grow"><p>{_e(a.get('description', ''))}</p>
      <p style="color:var(--g);opacity:.75">{
        'chart below' if a['symbol'] in drawn
        else _e(tv_symbol(a['symbol'], a.get('kind', 'equity'))) + ' — opens TradingView'}</p>
    </div><span class="chev">&rsaquo;</span></div></a>"""
                      for a in every_asset)

    chart_pages = "".join(f"""
<div class="page" id="c-{_e(c['symbol'].replace('.', '_').replace('-', '_'))}"><div class="wrap">
  <a class="back" href="#charts">&lsaquo; Charts</a>
  <div class="card call"><div class="sig" style="font-size:24px">{_e(c['symbol'])}</div>
    <div class="sub">{_e(c.get('kind', ''))} &middot; last {c.get('days', 180)} days</div></div>
  {c['block']}
</div></div>""" for c in data.get("charts", []))

    # Live cards only, strongest first. Ideas expire fast; a card that cannot
    # say whether its window is open is a dead row taking the place of one
    # that is still actionable.
    all_opps = data.get("opportunities", [])
    opps = _live_ideas(data)
    dropped = len(all_opps) - len(opps)
    empty_ideas = ('<div class="card"><p>Nothing new. The scan runs every four '
                   'hours and speaks only when something it has not already '
                   'shown you turns up.</p></div>')
    def _one_idea(i, o):
        return f"""
  <a href="#i-{i}"><div class="tile">
    <span class="pip" style="background:{_idea_state(o)[0]}"></span>
    <b>{_e(o['kind'])}</b>
    <div class="grow"><p style="color:var(--w);font-weight:600">{_e(o['title'])}</p>
      <p>{_e(o['summary'][:110])}</p>
      <p style="color:{_idea_state(o)[0]};font-weight:600">{_e(_idea_state(o)[1])}</p>
      {_bar("ready", _idea_state(o)[2], _idea_state(o)[0])}
      <p class="what-sm">{_e(_idea_eta(o))}</p></div>
    <span class="chev">&rsaquo;</span></div></a>"""
    # Finished = the case is answered (ready to act, bar at 100). Unfinished =
    # still being checked. Two rows on the landing, each opening its own page.
    finished = [(i, o) for i, o in enumerate(opps) if _idea_state(o)[2] >= 100]
    unfinished = [(i, o) for i, o in enumerate(opps) if _idea_state(o)[2] < 100]
    idea_cards = "" if not opps else f"""
  <a href="#ideas-finished"><div class="card row">
    <span class="pip" style="background:{'var(--green)' if finished else 'var(--faint)'};margin-top:0"></span>
    <div class="grow"><h3>Finished <span class="what-sm">({len(finished)})</span></h3>
      <p class="what-sm">The case is answered — ready to act on.</p></div>
    <span class="chev">&rsaquo;</span></div></a>
  <a href="#ideas-unfinished"><div class="card row">
    <span class="pip" style="background:{'var(--amber)' if unfinished else 'var(--faint)'};margin-top:0"></span>
    <div class="grow"><h3>Unfinished <span class="what-sm">({len(unfinished)})</span></h3>
      <p class="what-sm">Still being checked — not ready yet.</p></div>
    <span class="chev">&rsaquo;</span></div></a>"""
    # The two sub-pages.
    finished_page = f"""
<div class="page" id="ideas-finished"><div class="wrap">
  <a class="back" href="#ideas">&lsaquo; Ideas</a>
  <div class="card"><h1>Finished</h1><p class="what-sm">Ideas whose case is
  answered and ready to act on.</p></div>
  {"".join(_one_idea(i, o) for i, o in finished) or '<div class="card"><p>None ready yet.</p></div>'}
</div></div>"""
    unfinished_page = f"""
<div class="page" id="ideas-unfinished"><div class="wrap">
  <a class="back" href="#ideas">&lsaquo; Ideas</a>
  <div class="card"><h1>Unfinished</h1><p class="what-sm">Ideas still being
  checked, with how far each has to go.</p></div>
  {"".join(_one_idea(i, o) for i, o in unfinished) or '<div class="card"><p>Nothing in checking.</p></div>'}
</div></div>"""
    if dropped:
        idea_cards += (f'<p class="what-sm">{dropped} card(s) hidden: their '
                       'coverage never gave dates, so whether the window is '
                       'open cannot be known. Dropped rather than guessed.</p>')

    # Same list, same order — iterating the unfiltered set here would make
    # every #i-N link point at the wrong card.
    idea_pages = "".join(f"""
<div class="page" id="i-{i}"><div class="wrap">
  <a class="back" href="#ideas">&lsaquo; Ideas</a>
  <div class="card call"><div class="sig" style="color:{_e(o['colour'])};font-size:20px">
    {_e(o['kind'])}</div>
    <div class="sub">{_e(o['title'])}</div>
    <p class="what">{_e(o['verdict'])}</p></div>
  <h4>What it says</h4>
  <div class="card"><p>{_e(o['summary'])}</p></div>
  <h4>Money</h4>
  <div class="card"><p>{_e(o['money'])}</p></div>
  {'<h4>Already answered</h4><div class="card"><ul>' +
   ''.join(f'<li>{_e(a)}</li>' for a in o['answered']) + '</ul></div>'
   if o['answered'] else ''}
  {'<h4>You would have to find out</h4><div class="card"><ul>' +
   ''.join(f'<li>{_e(q)}</li>' for q in o['unanswered']) + '</ul></div>'
   if o['unanswered'] else ''}
  <h4>Where it came from</h4>
  <div class="card"><p>{_e('; '.join(tidy_source(x) for x in o['sources'][:3]) or 'no source recorded')}</p>
    <p style="margin-top:10px">This is not a forecast. It is a case someone
    could make, with the parts that are settled separated from the parts that
    are not.</p></div>
</div></div>""" for i, o in enumerate(opps))

    # The board's dropped-names list was rendered here for the board page,
    # which is now backend-only. The graveyard itself is still kept.
    from datetime import datetime, timezone

    raw_gen = data.get("generated_at", "")
    stamp = raw_gen[:16].replace("T", " ")
    # "updated Nh ago" and an overdue flag, computed here so the page needs no
    # JavaScript (a long-standing design rule these reports keep). A run is due
    # every 3 hours; past 4 the data is late and the dot is coloured to show it.
    fresh_label, overdue = f"{stamp} UTC", False
    if raw_gen:
        try:
            gen = datetime.fromisoformat(raw_gen)
            if gen.tzinfo is None:
                gen = gen.replace(tzinfo=timezone.utc)
            mins = max(0, int((datetime.now(timezone.utc) - gen).total_seconds() // 60))
            if mins < 60:
                fresh_label = f"updated {mins} min ago"
            elif mins < 1440:
                fresh_label = f"updated {round(mins / 60)}h ago"
            else:
                fresh_label = f"updated {round(mins / 1440)}d ago"
            overdue = mins > 240
        except ValueError:
            pass
    dot_style = ' style="background:#e5484d"' if overdue else ""
    # A page built from sample data must say so. Otherwise it looks exactly like
    # your own results, and the numbers on it are somebody else's.
    demo_banner = ("" if not data.get("is_sample") else
                   '<div class="card" style="border-color:#ffd93d">'
                   '<p style="color:#ffd93d;font-weight:700">SAMPLE DATA</p>'
                   '<p>This page was built from made-up records to show the layout. '
                   'Run <code>python -m sigbot.runner publish</code> to replace it '
                   'with your own.</p></div>')

    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8">
<!-- Reload every 10 minutes so a tab left open on a desktop keeps up with
     the file, which publish rewrites every 30. It costs the reader their
     scroll position, which is the trade: a stale page that looks current is
     worse than a page that jumps. On a phone the file is static, so this
     simply re-reads the same bytes and changes nothing. -->
<meta http-equiv="refresh" content="600">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#0a0a0f">
<title>Sigbot</title><style>{CSS}</style></head><body>

<div id="home"><div class="wrap">
  <div class="top"><span class="brand">Sig<em>bot</em></span><span class="stamp" title="{_e(stamp)} UTC"><i class="dot"{dot_style}></i>{_e(fresh_label)}</span></div>
  {demo_banner}
  <div class="hero">
    <div class="card call">
      <div class="eyebrow"><span class="dot"></span>Verification status</div>
      <h1>{proven} of {total} proven</h1>
      <p class="lead">{_e(h['message'])}</p>
      <div class="meter"><i style="width:{max((proven / max(total, 1)) * 100, 2):.0f}%"></i></div>
      <p class="what-sm">{h['observations_total']:,} predictions checked so far. Each one
      only counts once we know how it turned out.</p></div>
    <div class="card stat"><p class="what-sm">Daily predictions</p>
      <div class="statrow"><span class="num">{h.get('predictions_today', 0):,}</span>
        <span class="live">Today</span></div>
      <p class="what-sm" style="margin-top:auto">Made since the last reset ·
      resets each day. {proven} / {total} models proven.</p></div>
  </div>
  <div class="sechead">
    <div><h2 style="margin:0">What it watches</h2>
      <p class="what-sm">Real records. Real checks. No noise.</p></div>
    <span class="seccount">{len(data['models']):02d} systems</span>
  </div>
  <div class="grid2">{cards}</div>
  <div class="card foot"><div class="grow">
    <h3 style="text-transform:none;letter-spacing:0;font-size:17px;color:var(--text)">
      Same data as everyone. A different way of seeing it.</h3>
    <p class="what-sm">Sigbot does not predict for attention. It records, verifies,
    and only alerts when the record has earned the right.</p></div></div>
  <p class="note">{_e(data.get('disclaimer', ''))}</p>
</div></div>
{"".join(_model_page(m) for m in data["models"])}
{"".join(_sector_detail_pages(m) for m in data["models"] if m.get("id") == "opportunity")}

<!-- The board is backend-only. It still rotates the watchlist and keeps its
     graveyard; it no longer has a page. With the 100-name ceiling gone it was
     a list of hundreds of "Building — 0 of 25 checks" rows that told a
     visitor nothing, and every model page already shows what matters. -->

<div class="page" id="charts"><div class="wrap">
  <div class="top"><span class="brand">Charts</span>
    <span class="stamp">{len(b.get("assets", []))} assets</span></div>
  <p class="lead" style="margin-bottom:8px">Tap any name to open its chart in
  TradingView. On a phone this launches the TradingView app.</p>
  <p class="note" style="padding-top:0">{_e(indicator_note())}</p>
  {charts or empty}
  <p class="note">Charts are drawn here as plain markup, with the indicators the
  models actually compute already on them. No JavaScript, so they render from
  Files on an iPhone. Assets without a drawn chart fall back to a TradingView
  link.</p>
</div></div>
{chart_pages}

<div class="page" id="ideas"><div class="wrap">
  <div class="top"><span class="brand">Ideas</span>
    <span class="stamp">{len(opps)} open</span></div>
  <p class="lead" style="margin-bottom:8px">Things worth a look, from the news.
  The colour says how complete the case is — never how likely it is to work.</p>
  <p class="note" style="padding-top:0">Nothing here has been scored against
  outcomes, and single events cannot be: an IPO or a policy change happens once,
  so there is nothing to compare a new one against. This is material to think
  about, not a signal.</p>
  <p class="lead">Green means enough of the case is answered to act on.
  Grey means it is not, and the bar shows how far short it falls. Anything
  already expired, or that cannot be answered before its own window shuts, is
  removed rather than shown.</p>
  <div class="board-status">
    <span><i class="pip" style="background:var(--green)"></i>ready to act</span>
    <span><i class="pip" style="background:var(--faint)"></i>still short</span>
  </div>
  {idea_cards or empty_ideas}
</div></div>
{finished_page}
{unfinished_page}
{idea_pages}

<div class="page" id="learned"><div class="wrap">
  <div class="top"><span class="brand">Top picks</span>
    <span class="stamp">{len(_wins(learning))} of {len(learning)} came good</span></div>
  <p class="lead" style="margin-bottom:14px">The calls that worked. Every
  prediction — wins and misses alike — still enters the learning loop and the
  paper record; this page shows what came good so the shape of what works is
  readable at a glance. The misses are not hidden: they are priced in the
  paper P&amp;L, in full, every day.</p>
  {"".join(_feed_card(e, "learned", "#00e676") for e in _wins(learning)) or empty}
</div></div>
{"".join(_learned_detail(e) for e in learning)}

<div class="page" id="paper"><div class="wrap">
  <div class="top"><span class="brand">Paper portfolio</span>
    <span class="stamp">{_e(_paper_stamp(data))}</span></div>
  <p class="lead">Being right and making money are different questions. This
  replays every scored prediction as a position, charges real costs both ways,
  and reports what the signals would actually have paid. No broker is
  connected and no order was placed.</p>
  {_paper_body(data)}
  <p class="note">The replay follows models that have not cleared their skill
  gate. Finding out whether they are worth money is exactly what it is for,
  and the answer is allowed to be no.</p>
</div></div>
<div class="page" id="benchmarks"><div class="wrap">
  <div class="top"><span class="brand">Benchmarks</span>
    <span class="stamp">daily / monthly / yearly</span></div>
  <p class="lead">Did the paper account beat the index over each window? Each
  row measures only the current period — the daily row resets each day, the
  monthly each month, the yearly each year.</p>
  {_benchmark_rows(data)}
  <p class="note">The target is the index return over the same window — the bar
  the account must clear to be worth running. Beating it on one day is noise;
  the monthly and yearly rows are the ones that matter.</p>
</div></div>
<div class="page" id="predictions"><div class="wrap">
  <div class="top"><span class="brand">Predictions</span>
    <span class="stamp">every model that forecasts</span></div>
  <p class="lead">Each model that makes predictions, and how many it has
  scored. Tap one to see its predictions, grouped by how long they are held
  (intra-day, short-term, long-term).</p>
  {_predictions_rows(data)}
</div></div>
{_prediction_pages(data)}
<div class="page" id="picks"><div class="wrap">
  <div class="top"><span class="brand">Suggested picks</span>
    <span class="stamp">{_e(_picks_stamp(data))}</span></div>
  <p class="lead">Names the paper record has actually paid on. Confidence is
  how much of that record is profit, weighted down when the sample is thin —
  three winning trades is not the same evidence as thirty.</p>
  {_picks_rows(data)}
  <p class="note">Derived from paper trading, which is a simulation. A name
  here is a place to look, not a call to act, and every one of them also
  appears on the board with its own record.</p>
</div></div>
{_pick_pages(data)}
<div class="page" id="pnl"><div class="wrap">
  <div class="top"><span class="brand">Daily P&amp;L</span>
    <span class="stamp">{_e(_pnl_stamp(data))}</span></div>
  <p class="lead">One row per day of paper trading. Profits and losses both,
  because a day is only readable with its losses in it. No broker is
  connected and no order was placed.</p>
  {_pnl_rows(data)}
  <p class="note">The daily view resets; the record does not. Every trade —
  winning and losing — stays in the ledger and feeds the learning loop. This
  page shows one day at a time so it can be understood at a glance.</p>
</div></div>
{_pnl_detail_pages(data)}
<div class="page" id="missed"><div class="wrap">
  <div class="top"><span class="brand">Where it missed</span>
    <span class="stamp">{len(failures)} misses</span></div>
  <p class="lead" style="margin-bottom:14px">Every call that went wrong, and by how
  much. A good idea is still wrong roughly a third of the time — what matters is
  whether one reason keeps repeating.</p>
  {"".join(_feed_card(e, "missed", "#ff6b6b") for e in failures) or empty}
</div></div>
{"".join(_missed_detail(e) for e in failures)}

<nav class="nav">
  <a class="n-home" href="#home"><b>&#8962;</b><span>Home</span></a>
  <a class="n-pred" href="#predictions"><b>&#9673;</b><span>Predictions</span></a>
  <a class="n-ideas" href="#ideas"><b>&#10022;</b><span>Ideas</span></a>
  <a class="n-learn" href="#learned"><b>&#8599;</b><span>Top picks</span></a>
  <a class="n-paper" href="#paper"><b>&#8942;</b><span>Paper</span></a>
  <a class="n-picks" href="#picks"><b>&#9733;</b><span>Picks</span></a>
  <a class="n-pnl" href="#pnl"><b>&#8942;</b><span>Daily P&amp;L</span></a>
  <a class="n-bench" href="#benchmarks"><b>&#9878;</b><span>Benchmarks</span></a>
</nav>
<script>
/* Isolated, fail-safe enhancements. If anything throws, the static page — which
   is fully functional on its own — is left untouched. No framework, no network. */
(function () {{
  try {{
    var el = document.querySelector("[data-reset-at]");
    if (el) {{
      var target = new Date(el.getAttribute("data-reset-at"));
      var tick = function () {{
        try {{
          var ms = target - new Date();
          var live = el.querySelector(".countdown");
          if (ms <= 0) {{ if (live) live.textContent = "resetting…"; return; }}
          var h = Math.floor(ms / 3600000), m = Math.floor((ms % 3600000) / 60000);
          if (live) live.textContent = h + "h " + m + "m to reset";
        }} catch (e) {{}}
      }};
      tick(); setInterval(tick, 30000);
    }}
    var now = new Date();
    document.querySelectorAll("[data-expires]").forEach(function (row) {{
      try {{
        if (new Date(row.getAttribute("data-expires")) < now) row.style.display = "none";
      }} catch (e) {{}}
    }});
  }} catch (e) {{ /* static page stands on its own */ }}
}})();
</script>
</body></html>"""


def write_report(data_file: str | Path = "app/data.json",
                 out: str | Path = "app/sigbot-report.html") -> Path:
    data = json.loads(Path(data_file).read_text(encoding="utf-8"))
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_report(data), encoding="utf-8")
    return path


if __name__ == "__main__":
    import sys

    src = sys.argv[1] if len(sys.argv) > 1 else "app/data.json"
    dst = sys.argv[2] if len(sys.argv) > 2 else "app/sigbot-report.html"
    p = write_report(src, dst)
    print(f"wrote {p} ({p.stat().st_size / 1024:.0f} KB, no JavaScript)")

def _paper_stamp(data: dict) -> str:
    state = data.get("paper")
    if not state:
        return "not run yet"
    return f"{state.get('trades', 0):,} round trips"


def _paper_body(data: dict) -> str:
    """Today first: starting capital, today's percentage, today's win/loss
    count, and the capital that percentage leaves behind.

    The cumulative curve stays underneath because it is the only thing that
    can ever prove an edge — but it answers a different question from the one
    someone opens this page with, which is "what happened today".
    """
    state = data.get("paper") or {}
    if not state:
        return ('<div class="card"><p>The paper model has not run yet. It '
                'appears here once the first scored predictions carry both an '
                'entry and an exit price.</p></div>')

    days = state.get("days") or []
    start = state.get("starting_cash", 0)

    # If the newest day on record is not the actual calendar day (UTC), the new
    # day has opened with no trades yet: show a fresh zero, and the prior day
    # has already moved down into the record below. This is the "refresh to 0
    # at market open, move yesterday to P&L" behaviour.
    from datetime import datetime, timezone
    real_today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    newest = days[0] if days else None
    today: dict | None
    # New calendar day with no trades yet: synthesise an empty "today" so the
    # view shows 0 trades and yesterday drops into the record below — the
    # "refresh at market open" behaviour. The real days list is untouched.
    if newest and newest.get("date") != real_today:
        today = {"date": real_today, "pct": 0.0, "trades": [], "wins": 0,
                 "losses": 0, "opening": newest.get("closing", start),
                 "closing": newest.get("closing", start), "costs": 0.0,
                 "fresh": True}
    else:
        today = newest
    if today:
        pct = today.get("pct") or 0.0
        colour = ("var(--green)" if pct > 0
                  else "var(--red)" if pct < 0 else "var(--dim)")
        word = "up" if pct > 0 else "down" if pct < 0 else "flat"
        banner = f"""
  <div class="card call">
    <div class="eyebrow"><span class="dot"></span>Today · {_e(today.get('date', ''))}</div>
    <h1 style="color:{colour}">{abs(pct):.2f}% {word}</h1>
    <p class="lead">Opened the day on {today.get('opening', 0):,.0f} and sits
    at {today.get('closing', 0):,.0f} after {len(today.get('trades') or []):,}
    trade(s).</p>
  </div>
  <div class="stats">
    <div class="stat"><b>{start:,.0f}</b><span>Starting capital</span></div>
    <div class="stat"><b style="color:var(--green)">{today.get('wins', 0):,}</b>
      <span>Profitable today</span></div>
    <div class="stat"><b style="color:var(--red)">{today.get('losses', 0):,}</b>
      <span>Losing today</span></div>
  </div>
  <p class="what-sm">Today's figures reset at the end of the day. Every trade
  stays in the ledger and in Daily P&amp;L — only this view resets.</p>"""
    else:
        cycle = data.get("cycle", {})
        phase = cycle.get("phase", "")
        reason = {
            "reset": "The day has just reset. Predictions for the next session "
                     "are being made; trading begins when the market opens.",
            "predict": "The market is closed. Predictions are set for the next "
                       "session; paper trading places them when it opens.",
            "closed": "The market has closed for the day. Paper trading is off "
                      "until the next session.",
            "trade": "The market is open. Trades appear here as gated signals "
                     "are scored.",
        }.get(phase, "A trade appears here when a gated signal is scored.")
        reset = f'<p class="what-sm">{_e(cycle["reset_line"])}</p>' if cycle.get("reset_line") else ""
        banner = f"""
  <div class="card call">
    <div class="eyebrow"><span class="dot"></span>Today</div>
    <h1>No trades placed today</h1>
    <p class="lead">Starting capital {start:,.0f}. {_e(reason)}</p>
    {reset}
  </div>"""

    ret = state.get("total_return") or 0.0
    run_colour = ("var(--green)" if ret > 0
                  else "var(--red)" if ret < 0 else "var(--dim)")
    rows = "".join(
        f'''<div class="tile">
        <span class="pip" style="background:{
            "var(--green)" if row["pnl"] > 0 else "var(--red)"}"></span>
        <b>{_e(model)}</b><div class="grow">
        <p>{row["pnl"]:+,.0f} over {row["trades"]:,} trade(s)</p>
        <p>{(row.get("win_rate") or 0) * 100:.0f}% of them in profit,
        {row.get("costs", 0):,.0f} paid in costs</p></div></div>'''
        for model, row in sorted((state.get("by_model") or {}).items(),
                                 key=lambda kv: -kv[1]["pnl"]))

    return banner + f"""
  <h2>Since the record began (all time)</h2>
  <div class="stats">
    <div class="stat"><b style="color:{run_colour}">{ret * 100:+.2f}%</b>
      <span>All time</span></div>
    <div class="stat"><b>{state.get("equity", 0):,.0f}</b><span>Equity</span></div>
    <div class="stat"><b>{state.get("total_costs", 0):,.0f}</b><span>Costs paid</span></div>
  </div>
  <h2>Today's trades</h2>
  {_trade_rows(today)}
  {'<p class="note" style="border-top:1px solid var(--line);padding-top:14px;margin-top:18px">Everything below is the ALL-TIME record, not today. Today is shown above.</p>' if today and today.get("fresh") else ''}
  <h2>Which model paid (all time)</h2>
  <div class="tiles-grid">{rows or "<p>No trades yet.</p>"}</div>
  <p class="what-sm">{_e(state.get("verdict", ""))}</p>"""


def _paper_days(data: dict) -> list[dict]:
    state = data.get("paper") or {}
    return state.get("days") or []


def _pnl_stamp(data: dict) -> str:
    days = _paper_days(data)
    return f"{len(days)} day(s)" if days else "not run yet"


def _pnl_rows(data: dict) -> str:
    """A row per day, newest first, each linking to its own breakdown."""
    days = _paper_days(data)
    if not days:
        return ('<div class="card"><p>No paper trading days yet. A day appears '
                'here once the first gated signal has been scored.</p></div>')

    out = []
    for i, d in enumerate(days):
        up = (d.get("pct") or 0) >= 0
        colour = "var(--green)" if up else "var(--red)"
        out.append(f"""
  <a href="#pnl-{i}"><div class="tile">
    <span class="pip" style="background:{colour}"></span>
    <b>{_e(d.get('date', ''))}</b>
    <div class="grow"><p style="color:{colour};font-weight:600">
      {d.get('pct', 0):+.2f}% · {d.get('closing', 0):,.0f}</p>
      <p>{len(d.get('trades') or [])} trade(s), {d.get('wins', 0)} in profit,
      {d.get('losses', 0)} at a loss</p></div>
    <span class="chev">&rsaquo;</span></div></a>""")
    return "".join(out)


def _pnl_detail_pages(data: dict) -> str:
    """One page per day: the banner, then every trade that made it."""
    pages = []
    for i, d in enumerate(_paper_days(data)):
        up = (d.get("pct") or 0) >= 0
        colour = "var(--green)" if up else "var(--red)"
        trades = "".join(f"""
  <div class="tile"><span class="pip" style="background:{
        'var(--green)' if t.get('pnl', 0) > 0 else 'var(--red)'}"></span>
    <b>{_e(str(t.get('symbol', '')))}</b>
    <div class="grow"><p>{t.get('pnl', 0):+,.2f} on a
      {_e(str(t.get('side', '')))} of {t.get('size', 0):,.0f}</p>
      <p>{_e(str(t.get('model', '')))} · entry {t.get('entry_price', 0):,.4f}
      · exit {t.get('exit_price', 0):,.4f}
      · {t.get('gross_ret', 0) * 100:+.2f}% before costs</p></div></div>"""
            for t in (d.get("trades") or []))

        pages.append(f"""
<div class="page" id="pnl-{i}"><div class="wrap">
  <a class="back" href="#pnl">&lsaquo; Daily P&amp;L</a>
  <div class="card call">
    <div class="eyebrow"><span class="dot"></span>{_e(d.get('date', ''))}</div>
    <h1 style="color:{colour}">{d.get('pct', 0):+.2f}%</h1>
    <p class="lead">Opened at {d.get('opening', 0):,.0f}, closed at
    {d.get('closing', 0):,.0f}. {d.get('costs', 0):,.2f} paid in costs.</p>
  </div>
  <div class="stats">
    <div class="stat"><b>{len(d.get('trades') or [])}</b><span>Trades</span></div>
    <div class="stat"><b>{d.get('wins', 0)}</b><span>In profit</span></div>
    <div class="stat"><b>{d.get('losses', 0)}</b><span>At a loss</span></div>
  </div>
  <h2>Every trade that day</h2>
  <div class="tiles-grid">{trades or '<p>No trades.</p>'}</div>
</div></div>""")
    return "".join(pages)


def _shortcomings(failures: dict, wrong: int) -> str:
    """The failure breakdown in plain English.

    Saying a call missed is not useful; saying HOW it missed is the only part
    a person can act on. "Went the other way" and "right but too small to
    cover costs" call for different responses, and lumping them together
    hides that.
    """
    if not failures or wrong <= 0:
        return ("<p>Nothing has gone wrong yet, which with few checks means "
                "very little either way.</p>")

    plain = {
        "direction_wrong": ("went the other way", "the call was simply "
                            "backwards — the price moved against it"),
        "magnitude_short": ("right but too small", "the direction was right "
                            "and the move was smaller than the cost of "
                            "trading it, so being right earned nothing"),
        "unexplained": ("no clean reason", "the move does not fit either "
                        "pattern — usually a quiet session where the price "
                        "drifted without a story"),
    }
    rows = []
    for mode, count in sorted(failures.items(), key=lambda kv: -kv[1]):
        if mode == "win" or not count:
            continue
        label, explain = plain.get(mode, (mode.replace("_", " "), ""))
        share = count / wrong * 100 if wrong else 0
        rows.append(f"<li><b>{_e(label)}</b> — {count:,} of the "
                    f"{wrong:,} misses ({share:.0f}%): {_e(explain)}.</li>")
    if not rows:
        return "<p>No breakdown recorded for these misses yet.</p>"
    return ("<ul>" + "".join(rows) + "</ul>"
            "<p>The split matters more than the total. A run of "
            "\u201cright but too small\u201d means the signal works and the "
            "horizon is too short to pay for itself; a run of "
            "\u201cwent the other way\u201d means it does not work.</p>")


def _null_note(model: dict) -> str:
    """Say what chance scores, without contradicting itself.

    The sentence used to read "chance scores 50% ... so that is the bar to
    beat, not 50%" whenever the fallback null was in use, which is nonsense on
    the page and undermines the one point it is making.
    """
    null = model.get("null_rate")
    if not null:
        return ("Chance has not been measured for this model yet, so the bar "
                "is assumed to be a straight coin flip.")
    if abs(null - 0.50) < 0.005:
        return ("Chance scores about 50% on this model's measure, so a coin "
                "flip is the bar.")
    return (f"Chance scores {null * 100:.0f}% on this model's measure, "
            "because a call only counts when the move also clears trading "
            "costs. That is the bar to beat, not 50%.")


def _asset_split(model: dict) -> str:
    """How many of this model's assets beat chance, and how many do not.

    Counted against the model's measured null, not against 50%. On a
    cost-filtered metric a 45% asset can be above chance and a 51% one below
    it, so splitting at 50% would put assets on the wrong side of the line.
    """
    alerts = model.get("alerts") or []
    if not alerts:
        return ""
    null = model.get("null_rate") or 0.50
    above = sum(1 for a in alerts if (a.get("rate") or 0) > null)
    below = len(alerts) - above
    ready = sum(1 for a in alerts if a.get("tier") not in (None, "SILENT"))
    return f"""
  <div class="stats">
    <div class="stat"><b>{len(alerts):,}</b><span>Assets checked</span></div>
    <div class="stat"><b style="color:var(--green)">{above:,}</b>
      <span>Above chance</span></div>
    <div class="stat"><b style="color:var(--red)">{below:,}</b>
      <span>Below chance</span></div>
  </div>
  <p class="what-sm">Split at {null * 100:.0f}%, this model's measured chance
  level — not at 50%. {ready:,} have cleared a tier.</p>"""


def _paper_by_symbol(data: dict) -> list[dict]:
    """Per-symbol paper results, best first, with a shrunk confidence.

    Raw win rate on a handful of trades is mostly luck, so confidence is
    shrunk toward zero by sample size: a 100% record on three trades scores
    below a 60% record on thirty. Without that, the page would rank noise
    first, which is the single most misleading thing a "suggested" list can
    do.
    """
    state = data.get("paper") or {}
    by_symbol: dict[str, dict] = {}
    for day in state.get("days") or []:
        for trade in day.get("trades") or []:
            sym = str(trade.get("symbol", ""))
            if not sym:
                continue
            row = by_symbol.setdefault(sym, {
                "symbol": sym, "trades": 0, "wins": 0, "pnl": 0.0,
                "model": str(trade.get("model", ""))})
            row["trades"] += 1
            row["pnl"] += trade.get("pnl", 0.0)
            if trade.get("pnl", 0.0) > 0:
                row["wins"] += 1

    from .stats import wilson_interval

    out = []
    for row in by_symbol.values():
        n = row["trades"]
        row["win_rate"] = row["wins"] / n if n else 0.0
        # The Wilson lower bound, exactly as every other number in this system
        # is computed. An ad-hoc shrinkage toward 0.5 still ranked a 100%
        # record on three trades above a 60% record on thirty, because a
        # posterior MEAN rewards a short lucky run. A lower bound does not,
        # and using the same tool everywhere means the pages are comparable.
        lower, _ = wilson_interval(row["wins"], n, 0.90) if n else (0.0, 0.0)
        row["confidence"] = max(0.0, min((lower - 0.5) * 200.0, 100.0))
        if row["pnl"] > 0:
            out.append(row)
    return sorted(out, key=lambda r: -r["confidence"])


def _picks_stamp(data: dict) -> str:
    picks = _paper_by_symbol(data)
    return f"{len(picks)} name(s)" if picks else "nothing yet"


def _benchmark_rows(data: dict) -> str:
    """Three rows — daily, monthly, yearly — each with a met/not-met check."""
    rows = data.get("benchmarks", [])
    if not rows:
        return ('<div class="card"><p>No benchmark data yet. It fills once the '
                'paper account has a day of results.</p></div>')
    out = []
    for r in rows:
        met = r.get("met")
        check = ("&#10003;" if met else "&#10007;")
        colour = "var(--green)" if met else "var(--red)"
        out.append(f"""
  <div class="card row">
    <span class="pip" style="background:{colour};margin-top:0"></span>
    <div class="grow"><h3>{_e(r.get('period', ''))}
      <span style="color:{colour};font-size:20px;float:right">{check}</span></h3>
      <p>{_e(r.get('detail', ''))}</p></div>
  </div>""")
    return "".join(out)


def _predictions_rows(data: dict) -> str:
    """One row per forecasting model, with a pass/fail checker, linking through
    to that model's page. Blanks between reset and the next prediction run."""
    MODEL_TITLES = {"stocks": "Stocks & funds", "crypto15m": "Crypto",
                    "news": "News", "contagion": "Follow-on moves",
                    "daily": "Daily outlook", "opportunity": "Opportunities"}
    # Item 1: the "Fixed predictions" banner is removed — no longer useful.
    out = []
    for m in data.get("models", []):
        mid = m.get("id", "")
        # Item 1: predictions page shows EVERY prediction made, not only the
        # 5+-check ones the board filters to. `made` is the raw count.
        made = m.get("made", 0) or m.get("resolved", 0)
        # right/total from scored predictions (how many the model got right).
        scored = m.get("resolved", 0)
        right = int(round((m.get("hit_rate") or 0) * scored)) if scored else 0
        colour = "var(--green)" if made else "var(--faint)"
        title = MODEL_TITLES.get(mid, mid.title())
        # Item 1: the count sits at the FAR RIGHT of the row.
        right_total = (f'<span class="rt">{right}/{scored} right</span>'
                       if scored else '<span class="rt">—</span>')
        # Item 1: just the number of predictions made, no "nothing clears the bar".
        detail = f"{made:,} prediction(s) made"
        out.append(f"""
  <a href="#pred-{_e(mid)}"><div class="card row">
    <span class="pip" style="background:{colour};margin-top:0"></span>
    <div class="grow"><h3>{_e(title)}</h3>
      <p class="what-sm">{_e(m.get('subtitle', ''))}</p>
      <p>{_e(detail)}</p></div>
    {right_total}
    <span class="chev">&rsaquo;</span></div></a>""")
    return "".join(out)


def _prediction_pages(data: dict) -> str:
    """A dedicated page per model (item 3): three horizon rows (intra-day /
    short-term / long-term) linking to sub-pages of predictions sorted by
    confidence. Separate from the model page."""
    from .daily_cycle import horizon_lead_line
    MODEL_TITLES = {"stocks": "Stocks & funds", "crypto15m": "Crypto",
                    "news": "News", "contagion": "Follow-on moves",
                    "daily": "Daily outlook", "opportunity": "Opportunities"}
    HZ = (("intra-day", "Held less than a day"),
          ("short-term", "Held days to a few weeks"),
          ("long-term", "Held weeks to months"))
    pages = []
    for m in data.get("models", []):
        mid = m.get("id", "")
        title = MODEL_TITLES.get(mid, mid.title())
        alerts = m.get("alerts", [])
        by_h: dict = {h: [] for h, _ in HZ}
        for a in alerts:
            by_h.setdefault(a.get("horizon", "short-term"), []).append(a)
        # The model's prediction landing: three horizon rows.
        rows = []
        for h, blurb in HZ:
            items = by_h.get(h, [])
            n = len(items)
            lead = horizon_lead_line(h)
            col = "var(--green)" if n else "var(--faint)"
            if n:
                rows.append(f"""
  <a href="#predh-{_e(mid)}-{h}"><div class="card row">
    <span class="pip" style="background:{col};margin-top:0"></span>
    <div class="grow"><h3>{h.replace('-', ' ').title()} <span class="what-sm">({n})</span></h3>
      <p class="what-sm">{blurb} &middot; {_e(lead)}</p></div>
    <span class="chev">&rsaquo;</span></div></a>""")
            else:
                rows.append(f"""
  <div class="card row" style="opacity:.45">
    <span class="pip" style="background:var(--faint);margin-top:0"></span>
    <div class="grow"><h3>{h.replace('-', ' ').title()} <span class="what-sm">(0)</span></h3>
      <p class="what-sm">{blurb} &middot; {_e(lead)}</p></div>
  </div>""")
        pages.append(f"""
<div class="page" id="pred-{_e(mid)}"><div class="wrap">
  <a class="back" href="#predictions">&lsaquo; Predictions</a>
  <div class="card"><h1>{_e(title)}</h1>
    <p class="what-sm">Predictions grouped by how long they are held.</p></div>
  {"".join(rows)}
</div></div>""")
        # A sub-page per horizon, predictions sorted by confidence.
        for h, blurb in HZ:
            items = by_h.get(h, [])
            if not items:
                continue
            items = sorted(items, key=lambda a: -(a.get("conviction") or a.get("lower") or 0))
            body = "".join(f"""
  <a href="#d-{_e(mid)}-{_e(a['symbol'])}"><div class="card row">
    <span class="pip" style="background:{'var(--green)' if a.get('scan_tier') == 'PROVEN' or (a.get('lower') or 0) > (a.get('null') or 0.5) else 'var(--faint)'};margin-top:0"></span>
    <div class="grow"><h3>{_e(a['symbol'])}</h3>
      <p>{_e(a.get('detail', ''))}</p>
      {f'<p class="what-sm">made {_e(a.get("made_at", ""))} · result {_e(a.get("result_at", ""))}</p>' if a.get("made_at") else ''}</div>
    <span class="chev">&rsaquo;</span></div></a>""" for a in items)
            pages.append(f"""
<div class="page" id="predh-{_e(mid)}-{h}"><div class="wrap">
  <a class="back" href="#pred-{_e(mid)}">&lsaquo; {_e(title)}</a>
  <div class="card"><h1>{h.replace('-', ' ').title()}</h1>
    <p class="what-sm">{blurb} &middot; sorted by confidence.</p></div>
  {body}
</div></div>""")
    return "".join(pages)


def _picks_rows(data: dict) -> str:
    picks = _paper_by_symbol(data)
    # Only link where the detail page actually exists. A pick can come from a
    # trade on a symbol the model no longer lists, and a link to a page that
    # was never rendered is a dead end on the one page meant to send you
    # somewhere useful.
    if not picks:
        return ('<div class="card"><p>No name has a profitable paper record '
                'yet. That is the expected state while the models are still '
                'below their bars, and an empty list is the honest one.</p>'
                '</div>')

    # Grouped by model (issue 7): each model's picks under its own heading,
    # rather than one flat list, so picks are read per model.
    from collections import defaultdict
    MODEL_TITLES = {"stocks": "Stocks & funds", "crypto15m": "Crypto",
                    "news": "News", "contagion": "Follow-on moves",
                    "daily": "Daily outlook", "opportunity": "Opportunities"}
    by_model = defaultdict(list)
    for row in picks:
        by_model[row.get("model", "other")].append(row)

    # Item 4: a landing of MODEL rows; clicking a model opens its picks page.
    out = []
    for model in sorted(by_model):
        n = len(by_model[model])
        out.append(f"""
  <a href="#picks-{_e(model)}"><div class="card row">
    <span class="pip" style="background:var(--green);margin-top:0"></span>
    <div class="grow"><h3>{_e(MODEL_TITLES.get(model, model.title()))}
      <span class="what-sm" style="float:right">{n} pick(s)</span></h3>
      <p class="what-sm">Names this model has paid on in paper.</p></div>
    <span class="chev">&rsaquo;</span></div></a>""")
    return "".join(out)


def _pick_pages(data: dict) -> str:
    """One page per model listing its paper-profitable picks (item 4)."""
    picks = _paper_by_symbol(data)
    if not picks:
        return ""
    from collections import defaultdict
    MODEL_TITLES = {"stocks": "Stocks & funds", "crypto15m": "Crypto",
                    "news": "News", "contagion": "Follow-on moves",
                    "daily": "Daily outlook", "opportunity": "Opportunities"}
    pages_avail = {f"{m['id']}-{a['symbol']}"
                   for m in data.get("models", []) for a in (m.get("alerts") or [])}
    by_model = defaultdict(list)
    for row in picks:
        by_model[row.get("model", "other")].append(row)
    out = []
    for model in sorted(by_model):
        rows_out = []
        for row in by_model[model]:
            conf = row["confidence"]
            colour = ("var(--green)" if conf >= 20
                      else "var(--amber)" if conf >= 5 else "var(--faint)")
            body = f"""<div class="card row">
    <span class="pip" style="background:{colour};margin-top:0"></span>
    <div class="grow"><h3>{_e(row['symbol'])}</h3>
      <p>Paper trading made {row['pnl']:+,.0f} across {row['trades']:,}
      trade(s), {row['win_rate'] * 100:.0f}% in profit.</p>
      {_bar("conf", conf, colour)}</div>
    <span class="chev">&rsaquo;</span></div>"""
            key = f"{row['model']}-{row['symbol']}"
            rows_out.append(f'<a href="#d-{_e(key)}">{body}</a>'
                            if key in pages_avail else body)
        out.append(f"""
<div class="page" id="picks-{_e(model)}"><div class="wrap">
  <a class="back" href="#picks">&lsaquo; Suggested picks</a>
  <div class="card"><h1>{_e(MODEL_TITLES.get(model, model.title()))}</h1>
    <p class="what-sm">Names this model has paid on in paper, best first.</p></div>
  {"".join(rows_out)}
</div></div>""")
    return "".join(out)


def _board_progress(asset: dict) -> tuple[float, float]:
    """(percent toward the trade bar, percent toward removal) for one asset.

    Both capped at 100 and floored at 0 so a bar never renders past its track
    or inverts. An asset with no checks reads 0 on both, which is correct: it
    is neither close to qualifying nor close to being dropped.
    """
    from .watchlist import RULES

    n = asset.get("n") or 0
    lower = asset.get("lower") or 0.0
    upper = asset.get("upper") or 0.0

    by_checks = min(n / RULES.green_min_n, 1.0) if RULES.green_min_n else 1.0
    by_rate = (min(lower / RULES.green_min_lower, 1.0)
               if RULES.green_min_lower else 1.0)
    ready = max(0.0, min(min(by_checks, by_rate) * 100, 100.0))

    # Removal needs enough checks AND an upper bound that has fallen BELOW the
    # drop ceiling. The first version had this inverted: it read a healthy
    # upper bound of 0.60 against a 0.52 ceiling as 85% of the way to being
    # dropped, so strong assets and doomed ones looked alike and the two bars
    # contradicted each other on the same row.
    #
    # Closeness now means what it says. Comfortably above the ceiling is 0;
    # at or below it, and with the checks to confirm, is 100.
    if not n or not upper:
        return ready, 0.0

    ceiling = RULES.drop_max_upper
    if upper <= ceiling:
        drop_rate = 1.0                      # already failing the ceiling
    else:
        # Fade in over the band just above the ceiling. Beyond it, zero.
        band = ceiling * 0.25
        drop_rate = max(0.0, 1.0 - (upper - ceiling) / band)

    drop_checks = min(n / RULES.drop_min_n, 1.0) if RULES.drop_min_n else 0.0
    drop = max(0.0, min(min(drop_checks, drop_rate) * 100, 100.0))
    return ready, drop


def _idea_precision(o: dict) -> float:
    """How much of this idea's case the coverage could answer, 0-100.

    Not a probability and not a forecast — the share of the fixed question set
    that reporting settled, which is the only measurable thing about a single
    unrepeatable event.
    """
    answered = len(o.get("answered") or [])
    unanswered = len(o.get("unanswered") or [])
    total = answered + unanswered
    return (answered / total * 100.0) if total else 0.0


def _idea_is_dead(o: dict) -> bool:
    """True for cards that can no longer be acted on.

    Undated listings go because there is no free way to find the window and
    inventing a date is the one thing this system must never do. Dated ones go
    once the window has shut — that case was missed at first precisely because
    the card HAD a date, so the undated filter could not see it.
    """
    text = f"{o.get('kind', '')} {o.get('summary', '')}".lower()
    if ("dates unknown" in text or "gives no dates" in text
            or "closed" in o.get("kind", "").lower()):
        return True

    import re
    from datetime import datetime, timezone

    months = {m: i for i, m in enumerate(
        ("jan", "feb", "mar", "apr", "may", "jun",
         "jul", "aug", "sep", "oct", "nov", "dec"), start=1)}
    today = datetime.now(timezone.utc).date()
    for day, mon in re.findall(r"(\d{1,2})\s+([A-Za-z]{3})", text):
        month = months.get(mon[:3].lower())
        if not month:
            continue
        try:
            when = today.replace(month=month, day=int(day))
        except ValueError:
            continue
        if (today - when).days > 2:
            return True
    return False


def _idea_state(o: dict) -> tuple[str, str, float]:
    """(colour, plain state, percent toward green) for one idea.

    Two colours only. Amber and grey both meant "not yet" while amber SORTED
    higher despite often carrying a weaker case, so the palette actively
    misled: the colour said one thing and the bar said another. Green now
    means the case is strong enough to act on; grey means it is not, and the
    bar says how far short it falls.
    """
    precision = _idea_precision(o)
    if precision >= GREEN_IDEA_AT:
        return "var(--green)", "Ready — the case is answered", 100.0
    toward = precision / GREEN_IDEA_AT * 100.0 if GREEN_IDEA_AT else 0.0
    return "var(--faint)", "Not enough answered yet", max(0.0, min(toward, 100.0))


def _idea_expected_days(o: dict) -> float | None:
    """Rough days until this idea's case could be complete, or None.

    Reporting arrives at whatever rate it arrives; with one scan every four
    hours, an unanswered question resolves in about a day when it resolves at
    all. This is an estimate and says so — its only job is to be compared
    against the expiry, because an idea that cannot be answered before its
    window shuts is not an idea.
    """
    unanswered = len(o.get("unanswered") or [])
    return None if not unanswered else unanswered * 1.0


def _idea_days_left(o: dict) -> float | None:
    """Days until the stated window shuts, or None when no date is given."""
    import re
    from datetime import datetime, timezone

    months = {m: i for i, m in enumerate(
        ("jan", "feb", "mar", "apr", "may", "jun",
         "jul", "aug", "sep", "oct", "nov", "dec"), start=1)}
    text = f"{o.get('kind', '')} {o.get('summary', '')}".lower()
    today = datetime.now(timezone.utc).date()
    soonest = None
    for day, mon in re.findall(r"(\d{1,2})\s+([A-Za-z]{3})", text):
        month = months.get(mon[:3].lower())
        if not month:
            continue
        try:
            when = today.replace(month=month, day=int(day))
        except ValueError:
            continue
        days = (when - today).days
        if days >= 0 and (soonest is None or days < soonest):
            soonest = float(days)
    return soonest


def _live_ideas(data: dict) -> list[dict]:
    """Ideas worth showing, strongest case first.

    Dropped here: anything already expired, and anything whose case cannot be
    completed before its own window shuts. The second is the important one —
    an idea that will still be unanswered on the day it closes was never
    actionable, and showing it just spends your attention on a foregone
    conclusion.
    """
    live = []
    for o in data.get("opportunities") or []:
        if _idea_is_dead(o):
            continue
        need = _idea_expected_days(o)
        left = _idea_days_left(o)
        if need is not None and left is not None and need > left:
            continue
        live.append(o)
    return sorted(live, key=lambda o: -_idea_precision(o))


def _wins(learning: list[dict]) -> list[dict]:
    """The calls that worked. Display-only.

    Every entry — hit or miss — is still stored, still fed to the learning
    loop, and still priced into the paper P&L. Filtering the PAGE is not
    filtering the RECORD.
    """
    return [e for e in learning if e.get("hit")]


def _board_state(ready: float, drop: float) -> tuple[str, str]:
    """Colour and plain-English state from the two distances.

    Derived from where an asset is HEADING, not from what tier it holds now.
    The tier is a label; these two numbers are the movement, and movement is
    what tells you where attention is worth spending.
    """
    if drop > ready:
        return "var(--red)", "Danger — losing ground"
    if ready >= 90:
        return "var(--green)", "Close — nearly ready"
    return "var(--faint)", "Building"


def _trade_rows(day: dict | None) -> str:
    """Every trade of the day: what, which way, and one word for the outcome.

    A row that says only "+2.11%" makes you work out what was bought and
    whether it worked. Name, direction and verdict, in that order, is the
    whole question answered in one line.
    """
    if not day or not (day.get("trades") or []):
        return ('<div class="card"><p>No trades today. The models only act '
                'when a signal clears its bar, and most days none does.</p>'
                '</div>')

    out = []
    for t in day.get("trades") or []:
        pnl = t.get("pnl", 0.0)
        won = pnl > 0
        colour = "var(--green)" if won else "var(--red)"
        word = "PROFIT" if won else "LOSS"
        side = str(t.get("side", "")).upper() or "BUY"
        out.append(f"""
  <div class="tile"><span class="pip" style="background:{colour}"></span>
    <b>{_e(str(t.get('symbol', '')))}</b>
    <div class="grow">
      <p style="color:{colour};font-weight:600">{_e(side)} &middot; {word}</p>
      <p>{pnl:+,.2f} on a position of {t.get('size', 0):,.0f},
      moved {t.get('gross_ret', 0) * 100:+.2f}% before costs</p>
      <p class="what-sm">Signal from {_e(str(t.get('model', '')))}.
      In at {t.get('entry_price', 0):,.4f}, out at
      {t.get('exit_price', 0):,.4f}.</p></div></div>""")
    return f'<div class="tiles-grid">{"".join(out)}</div>'


def _idea_eta(o: dict) -> str:
    """When this case might complete, against when its window shuts."""
    need = _idea_expected_days(o)
    left = _idea_days_left(o)
    if need is None:
        return "Every question answered."
    if left is None:
        return (f"About {need:.0f} more day(s) of reporting would finish the "
                "case. No closing date was given.")
    return (f"About {need:.0f} more day(s) of reporting would finish the case, "
            f"and the window shuts in {left:.0f}.")


def _bar(label: str, pct: float, colour: str) -> str:
    """One progress bar, or an empty track when there is nothing to show.

    A zero-width fill still rendered a visible stub, which read as "some
    progress" on an asset with no checks at all — the opposite of the truth.
    Nothing measured shows an empty track and a dash.
    """
    pct = max(0.0, min(float(pct or 0), 100.0))
    # Guard the ROUNDED value: 0.4 is greater than zero but formats as "0%",
    # which is exactly the stub this is meant to prevent.
    if round(pct) <= 0:
        # No track at all when there is nothing to measure. An empty track
        # still reads as a full grey bar on a phone, which is the opposite of
        # "nothing yet".
        return (f'<div class="dualbar dualbar-empty"><span>{label}</span>'
                f'<span>not yet</span></div>')
    return (f'<div class="dualbar"><span>{label}</span>'
            f'<i><b style="width:{pct:.0f}%;background:{colour}"></b></i>'
            f'<span>{pct:.0f}%</span></div>')


def _meter(pct: float, colour: str) -> str:
    """A filled meter, or an empty track when nothing has been measured.

    Same reason as _bar: a zero-width fill still drew a visible stub, so a
    model with no record looked like one with a little.
    """
    pct = max(0.0, min(float(pct or 0), 100.0))
    # Rounded, as in _bar: 0.4 is above zero but renders as "0%".
    #
    # NO <i> AT ALL when empty. In a meter the <i> IS the coloured fill, styled
    # display:block, so an <i> with no width stretches to 100% — an empty meter
    # drew as a FULL teal bar directly above "Nothing checked yet". The earlier
    # guard test only checked that no bar said width:0%, which removing the
    # width satisfied while making the bar full: it tested a proxy, not what a
    # person sees.
    if round(pct) <= 0:
        return '<div class="meter"></div>'
    return f'<div class="meter"><i style="width:{pct:.0f}%;background:{colour}"></i></div>'


def _scan_note(model: dict) -> str:
    """The legend for the stocks page, stated before the rows.

    A page mixing proven and unproven rows has to say so at the top. A reader
    who works out halfway down that half the list is experimental has already
    formed the wrong impression of the first half.
    """
    if model.get("id") != "stocks":
        return ""
    alerts = model.get("alerts") or []
    if not alerts:
        return ('<div class="card"><p>Nothing fired. The scan looks at every '
                'name it can reach and stays quiet on almost all of them — '
                'that is the usual outcome, and a quiet day costs nothing.'
                '</p></div>')
    proven = sum(1 for a in alerts if a.get("scan_tier") == "PROVEN")
    return f"""
  <div class="board-status">
    <span><i class="pip" style="background:var(--green)"></i>{proven} worth acting on</span>
    <span><i class="pip" style="background:var(--faint)"></i>{len(alerts) - proven} risky</span>
  </div>
  <p class="what-sm">Green means the reason this fired has worked in three
  separate stretches of history. Grey means it looks promising but has not
  proved itself — those are traded at a third of the size, on purpose, so the
  record that would settle it actually gets built.</p>"""


def _sector_rows(model: dict) -> str:
    """The 20 industry sector cards on the Opportunities page.

    Each card shows the sector, a readiness bar built from the asymmetry of the
    ventures inside it, and a count of worth-taking and risky ventures. Risky
    ones are labelled, never hidden. Tapping through would show the ventures;
    for now the card summarises them.
    """
    cards = model.get("sector_cards") or []
    if not cards:
        return ""
    out = ['<p class="what-sm" style="padding:0 4px 8px">The bar is APPEAL — '
           'how attractive a sector\'s ventures are by expected value. It is '
           'not a probability and not a predicted move.</p>']
    for c in cards:
        readiness = float(c.get("readiness", 0) or 0)
        worth = int(c.get("worth_taking", 0) or 0)
        risky = int(c.get("risky", 0) or 0)
        n = len(c.get("ventures", []))
        colour = "var(--green)" if worth else "var(--faint)"
        risky_tag = (f'<span class="badge" style="background:#e0a03022;'
                     f'color:#e0a030">{risky} risky</span>' if risky else "")
        sig = c.get("breadth_signal", "")
        timing_tag = ("" if not sig else
                      '<span class="badge" style="background:#2ecc7122;'
                      'color:#2ecc71">recovery-likely</span>' if sig == "recovery-likely"
                      else '<span class="badge" style="background:#e5484d22;'
                      'color:#e5484d">cooling</span>')
        # Plain-language, not a percentage that reads as a prediction. The
        # "appeal" bar is how attractive the ventures inside are (their
        # expected value), NOT a probability and NOT a predicted move.
        detail = (f"{worth} worth a small bet, {n} watched" if n
                  else "no live ventures yet")
        slug = _slug(c.get("sector", ""))
        out.append(f"""
    <a href="#sec-{slug}"><div class="card row">
      <span class="pip" style="background:{colour};margin-top:0"></span>
      <div class="grow"><h3>{_e(c.get('sector', ''))}  {risky_tag} {timing_tag}</h3>
        <p class="what-sm">{_e(c.get('blurb', ''))}</p>
        <p>{_e(detail)}</p>
        {_bar("appeal", readiness, colour)}</div>
      <span class="chev">&rsaquo;</span></div></a>""")
    return "".join(out)


def _slug(text: str) -> str:
    """A URL-safe id fragment from a sector or venture name."""
    import re
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40]


def _sector_detail_pages(model: dict) -> str:
    """One page per sector, listing its ventures as clickable rows, plus one
    page per venture with the full reasoning — mirroring the stocks drill-down.
    """
    cards = model.get("sector_cards") or []
    pages = []
    for c in cards:
        sector = c.get("sector", "")
        slug = _slug(sector)
        ventures = c.get("ventures", [])
        if ventures:
            rows = []
            for v in ventures:
                vslug = _slug(v.get("title", ""))
                vcol = "var(--green)" if "WORTH" in v.get("verdict", "") else "var(--faint)"
                vtag = ('<span class="badge" style="background:#e0a03022;'
                        'color:#e0a030">risky</span>' if v.get("risky") else "")
                rows.append(f"""
    <a href="#ven-{slug}-{vslug}"><div class="card row">
      <span class="pip" style="background:{vcol};margin-top:0"></span>
      <div class="grow"><h3>{_e(v.get('title', ''))}  {vtag}</h3>
        <p>{_e(v.get('verdict', ''))} &middot; upside {_e(str(v.get('upside', '')))}x</p></div>
      <span class="chev">&rsaquo;</span></div></a>""")
            body = "".join(rows)
        else:
            body = ('<div class="card"><p>No live ventures in this sector yet. '
                    'It stays quiet until a real opportunity is found.</p></div>')
        pages.append(f"""
<div class="page" id="sec-{slug}"><div class="wrap">
  <a class="back" href="#m-opportunity">&lsaquo; Opportunities</a>
  <div class="card"><h1>{_e(sector)}</h1>
    <p style="margin-bottom:10px">{_e(c.get('blurb', ''))}</p>
    <p class="what-sm">{c.get('worth_taking', 0)} worth a small bet, {len(ventures)} watched.</p>
  </div>
  {body}
</div></div>""")
        # A full page per venture.
        for v in ventures:
            vslug = _slug(v.get("title", ""))
            reasons = "".join(f"<li>{_e(r)}</li>" for r in v.get("reasons", [])) or "<li>—</li>"
            sources = "".join(f"<li>{_e(x)}</li>" for x in v.get("sources", [])) or "<li>no source recorded</li>"
            vcol = "var(--green)" if "WORTH" in v.get("verdict", "") else "var(--faint)"
            pages.append(f"""
<div class="page" id="ven-{slug}-{vslug}"><div class="wrap">
  <a class="back" href="#sec-{slug}">&lsaquo; {_e(sector)}</a>
  <div class="card call"><div class="sig" style="color:{vcol}">{_e(v.get('verdict', ''))}</div>
    <div class="sub">{_e(v.get('title', ''))}</div></div>
  <p class="lead">{_e(v.get('thesis', ''))}</p>

  <h4>The asymmetry</h4>
  <div class="card"><dl>
    <dt>Upside if it works</dt><dd>{_e(str(v.get('upside', '')))}x the amount risked</dd>
    <dt>Expected value</dt><dd>{_e(str(v.get('ev', '')))}x</dd>
    <dt>Downside</dt><dd>capped and survivable</dd>
  </dl>
  <p style="margin-top:10px">A bet is worth a small stake when the downside is
  bounded and the expected value is positive — regardless of how likely it is.
  You do not need it to be certain; you need being wrong to be survivable.</p></div>

  <h4>Why it is risky</h4>
  <div class="card"><ul>{reasons}</ul></div>

  <h4>Where the evidence comes from</h4>
  <div class="card"><ul>{sources}</ul>
    <p style="margin-top:10px">This is not a forecast. It is a case someone
    could make, with the parts that are settled separated from the parts that
    are not.</p></div>
</div></div>""")
    return "".join(pages)


HORIZONS = (("intra-day", "Held less than a day"),
            ("short-term", "Held days to a few weeks"),
            ("long-term", "Held weeks to months"))


def _horizon_groups(model: dict, row_fn) -> str:
    """Three horizon rows that LINK to separate pages (intra-day / short-term /
    long-term). Clicking a row opens that horizon's own page, like the sector
    cards. row_fn is kept for the page bodies (see _horizon_pages).

    Only horizons with at least one item are shown as active links; an empty
    horizon is greyed and not clickable, so the classifier is honest about
    where there is anything to see.
    """
    alerts = model.get("alerts") or []
    mid = model.get("id", "")
    by_h: dict[str, list] = {h: [] for h, _ in HORIZONS}
    for a in alerts:
        by_h.setdefault(a.get("horizon", "short-term"), []).append(a)
    out = []
    for h, blurb in HORIZONS:
        items = by_h.get(h, [])
        n = len(items)
        title = h.replace("-", " ").title()
        if n:
            out.append(f"""
  <a href="#h-{_e(mid)}-{h}"><div class="card row">
    <span class="pip" style="background:var(--green);margin-top:0"></span>
    <div class="grow"><h3>{title} <span class="what-sm">({n})</span></h3>
      <p class="what-sm">{blurb}</p></div>
    <span class="chev">&rsaquo;</span></div></a>""")
        else:
            out.append(f"""
  <div class="card row" style="opacity:.45">
    <span class="pip" style="background:var(--faint);margin-top:0"></span>
    <div class="grow"><h3>{title} <span class="what-sm">(0)</span></h3>
      <p class="what-sm">Nothing held over this horizon yet.</p></div>
  </div>""")
    return "".join(out)


def _horizon_pages(model: dict, row_fn) -> str:
    """One separate page per non-empty horizon, listing its assets sorted by
    confidence. Reached from the horizon rows on the model page."""
    alerts = model.get("alerts") or []
    mid = model.get("id", "")
    name = model.get("name", mid.title())
    by_h: dict[str, list] = {h: [] for h, _ in HORIZONS}
    for a in alerts:
        by_h.setdefault(a.get("horizon", "short-term"), []).append(a)
    pages = []
    for h, blurb in HORIZONS:
        items = by_h.get(h, [])
        if not items:
            continue
        items = sorted(items, key=lambda a: -(a.get("conviction") or a.get("lower") or 0))
        title = h.replace("-", " ").title()
        pages.append(f"""
<div class="page" id="h-{_e(mid)}-{h}"><div class="wrap">
  <a class="back" href="#m-{_e(mid)}">&lsaquo; {_e(name)}</a>
  <div class="card"><h1>{title}</h1>
    <p class="what-sm">{blurb} &middot; sorted by confidence.</p></div>
  {"".join(row_fn(a) for a in items)}
</div></div>""")
    return "".join(pages)


def _scan_rows(model: dict) -> str:
    """Stocks rows: a dot, two bars, and a link through to the full page.

    Two bars, as on the board, because one number cannot answer both questions
    a reader has. Conviction is how much of the evidence bar the REASON has
    cleared; record is how far this NAME has come toward a verdict of its own.
    A row can be high on one and low on the other, and that combination is the
    most useful thing on the page.
    """
    alerts = model.get("alerts") or []
    if not alerts:
        return ""

    # Grouped into the three horizon rows; each expands to its assets, sorted
    # proven-first then by conviction inside the group.
    for a in alerts:
        a["_sortkey"] = (0 if a.get("scan_tier") == "PROVEN" else 1,
                         -(a.get("conviction") or 0), a.get("symbol", ""))
    model = dict(model)
    model["alerts"] = sorted(alerts, key=lambda a: a["_sortkey"])
    return _horizon_groups(model, _one_scan_row)


def _one_scan_row(a: dict) -> str:
    proven = a.get("scan_tier") == "PROVEN"
    colour = "var(--green)" if proven else "var(--faint)"
    label = "Worth acting on" if proven else "Risky — unproven"
    conviction = a.get("conviction") or 0
    return f"""
  <a href="#d-stocks-{_e(a['symbol'])}"><div class="card row">
    <span class="pip" style="background:{colour};margin-top:0"></span>
    <div class="grow"><h3>{_e(a['symbol'])}</h3>
      <p style="color:{colour};font-weight:600">{label}</p>
      {f'<p class="what-sm">{_e(a["description"])}</p>' if a.get("description") else ''}
      <p>{_e(a.get('detail', ''))}</p>
      {_bar("confidence", conviction, colour)}
      {_bar("ready to act", a.get("to_trade", 0), colour)}</div>
    <span class="chev">&rsaquo;</span></div></a>"""
