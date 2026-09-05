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
import json
from pathlib import Path

from .charts import chart_url, indicator_note, tv_symbol
from .expectancy import size_position

ACCENT = {"teal": "#00d4aa", "purple": "#7c4dff", "red": "#ff6b6b", "green": "#00e676"}
TIER_COLOR = {"TRADE": "#00e676", "CAUTION": "#ffd93d", "WATCH": "#00d4aa", "SILENT": "#8b8b9a"}
TIER_PLAIN = {
    "TRADE": "Proven enough to act on",
    "CAUTION": "Promising, small size only",
    "WATCH": "Worth watching, not acting",
    "SILENT": "Still collecting",
}

MECHANISM = {
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
body{color:var(--text);
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
.hero .stat::before{content:"LIVE RECORD";display:block;margin-bottom:28px;
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


def _call(model: dict, a: dict) -> tuple[str, str, str]:
    tier, n = a.get("tier", "SILENT"), a.get("resolved", 0)
    if tier in ("TRADE", "CAUTION"):
        return "BUY", TIER_COLOR[tier], f"beats a coin flip across {n:,} checks"
    if tier == "WATCH":
        return "HOLD", TIER_COLOR["WATCH"], "there is something here, but not enough to act on"
    return "HOLD", TIER_COLOR["SILENT"], f"only {n} checks so far — too few to call"


def _detail(model: dict, a: dict) -> str:
    sym, n = a["symbol"], a.get("resolved", 0)
    sig, col, reason = _call(model, a)
    rate, floor = model.get("hit_rate"), model.get("lower_bound")
    mech, blind = MECHANISM.get(model["id"], ("", ""))
    edge = (floor - 0.50) if floor is not None else None
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

  <h4>Where the number comes from</h4>
  <div class="card"><dl>
    <dt>Times we checked</dt><dd>{n:,}</dd>
    <dt>Times we were right</dt><dd>{_pct(rate)}</dd>
    <dt>Worst case, realistically</dt><dd style="color:{col}">{_pct(floor)}</dd>
    <dt>A coin flip would give</dt><dd>50%</dd>
    <dt>Better than a coin by</dt>
    <dd style="color:{'var(--green)' if edge and edge > 0 else 'var(--red)'}">
      {'—' if edge is None else f'{edge * 100:+.0f} points'}</dd>
  </dl>
  <div class="meter"><i style="width:{min(100, (floor or 0) * 100):.0f}%;background:{col}"></i></div>
  <p>Use the worst case, not the headline number. With {n:,} checks behind it,
  that is what the record actually supports — the higher figure is the luckiest
  reading of the same data. Few checks means a low worst case even when the
  headline looks good. That is the honest answer, not a broken one.</p></div>

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
    rows = "".join(f"""
    <a href="#d-{_e(m['id'])}-{_e(a['symbol'])}"><div class="card row">
      <div class="av" style="background:{col}1f;border-color:{col}59;color:{col}">
        {_e(a['symbol'][:3])}</div>
      <div class="grow"><h3>{_e(a['symbol'])}</h3>
        {f'<p class="what-sm">{_e(a["description"])}</p>' if a.get("description") else ''}
        <p>{_e(a['detail'])}</p></div>
      <span class="chev">&rsaquo;</span></div></a>""" for a in m["alerts"])
    return f"""
<div class="page" id="m-{_e(m['id'])}"><div class="wrap">
  <a class="back" href="#home">&lsaquo; Home</a>
  <div class="card"><h1>{_e(m['name'])}</h1>
    <p style="margin-bottom:10px">{_e(m['subtitle'])}</p>
    <span class="badge" style="background:{tc}1f;color:{tc}">{_e(TIER_PLAIN.get(m['tier'], m['tier']))}</span>
    <div class="meter"><i style="width:{(m.get('lower_bound') or 0) * 100:.0f}%;background:{tc}"></i></div>
    <p>{_e(m['status_line'])}</p>
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
  <h2>What it is watching</h2>
  {rows or '<div class="card"><p>Nothing has been checked for this one yet. It stays quiet until it has something to show.</p></div>'}
  <p class="note">Tap any row for the full reasoning.</p>
</div></div>
{"".join(_detail(m, a) for a in m["alerts"])}"""


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
        <span class="badge" style="background:{TIER_COLOR.get(m['tier'])}1f;
          color:{TIER_COLOR.get(m['tier'])};margin-top:5px">
          {_e(TIER_PLAIN.get(m['tier'], m['tier']))}</span></div>
      <span class="chev">&rsaquo;</span></div></a>""" for m in data["models"])

    empty = ('<div class="card"><p>Nothing checked yet. Come back once the '
             'collector has run for a few days.</p></div>')

    b = data.get("board", {})

    def _tile(a):
        return f"""
  <div class="tile"><span class="pip" style="background:{_e(a['colour'])}"></span>
    <b>{_e(a['symbol'])}</b>
    <div class="grow"><p style="color:{_e(a['colour'])}">{_e(a['flag_label'])}</p>
      <p>{_e(a['reason'])}</p></div></div>"""

    # Stocks and crypto are different games — different hours, different costs,
    # different volatility. One undivided wall of a hundred names made the
    # board read as noise; two sections make it read as two answers.
    stocks = [a for a in b.get("assets", []) if a.get("kind") != "crypto"]
    coins = [a for a in b.get("assets", []) if a.get("kind") == "crypto"]
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

    opps = data.get("opportunities", [])
    empty_ideas = ('<div class="card"><p>Nothing new. The scan runs every four '
                   'hours and speaks only when something it has not already '
                   'shown you turns up.</p></div>')
    idea_cards = "".join(f"""
  <a href="#i-{i}"><div class="tile">
    <span class="pip" style="background:{_e(o['colour'])}"></span>
    <b>{_e(o['kind'])}</b>
    <div class="grow"><p style="color:var(--w);font-weight:600">{_e(o['title'])}</p>
      <p>{_e(o['summary'][:110])}</p></div>
    <span class="chev">&rsaquo;</span></div></a>""" for i, o in enumerate(opps))

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
  <div class="card"><p>{_e('; '.join(o['sources'][:3]) or 'no source recorded')}</p>
    <p style="margin-top:10px">This is not a forecast. It is a case someone
    could make, with the parts that are settled separated from the parts that
    are not.</p></div>
</div></div>""" for i, o in enumerate(opps))

    dead = b.get("graveyard", [])
    grave = ("" if not dead else
             '<h2>Dropped</h2><p class="note" style="padding-top:0">Kept with their '
             'numbers. Dropping the weak and keeping the strong is how survivorship '
             'bias gets built on purpose, so nothing disappears quietly.</p>' +
             "".join(f"""
  <div class="tile"><span class="pip" style="background:#8b8b9a"></span>
    <b>{_e(g['symbol'])}</b><div class="grow"><p>{_e(g['reason'])}</p></div></div>"""
                     for g in dead))
    stamp = data.get("generated_at", "")[:16].replace("T", " ")
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
  <div class="top"><span class="brand">Sig<em>bot</em></span><span class="stamp"><i class="dot"></i>{_e(stamp)} UTC</span></div>
  {demo_banner}
  <div class="hero">
    <div class="card call">
      <div class="eyebrow"><span class="dot"></span>Verification status</div>
      <h1>{proven} of {total} proven</h1>
      <p class="lead">{_e(h['message'])}</p>
      <div class="meter"><i style="width:{max((proven / max(total, 1)) * 100, 2):.0f}%"></i></div>
      <p class="what-sm">{h['observations_total']:,} predictions checked so far. Each one
      only counts once we know how it turned out.</p></div>
    <div class="card stat"><p class="what-sm">Verified predictions</p>
      <div class="statrow"><span class="num">{h['observations_total']:,}</span>
        <span class="live">Live</span></div>
      <p class="what-sm" style="margin-top:auto">{proven} / {total} proven ·
      counted only after the outcome is known</p></div>
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

<div class="page" id="board"><div class="wrap">
  <div class="top"><span class="brand">The board</span>
    <span class="stamp">{b.get("size", 0)} assets</span></div>
  <p class="lead" style="margin-bottom:10px">{_e(b.get("note", ""))}</p>
  <div class="board-status">
    <span><i class="pip" style="background:var(--green)"></i>{b.get("counts", dict()).get("GREEN", 0)} ready</span>
    <span><i class="pip" style="background:var(--amber)"></i>{b.get("counts", dict()).get("AMBER", 0)} risky</span>
    <span><i class="pip" style="background:var(--red)"></i>{b.get("counts", dict()).get("RED", 0)} avoid</span>
    <span><i class="pip" style="background:var(--faint)"></i>{b.get("counts", dict()).get("TESTING", 0)} testing</span>
  </div>
  <div class="legend">
    <span><i class="pip" style="background:#00e676"></i>{b.get("counts", {}).get("GREEN", 0)} ready</span>
    <span><i class="pip" style="background:#ffd93d"></i>{b.get("counts", {}).get("AMBER", 0)} risky</span>
    <span><i class="pip" style="background:#ff6b6b"></i>{b.get("counts", {}).get("RED", 0)} avoid</span>
  </div>
  {tiles or empty}
  {grave}
</div></div>

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
  <div class="legend">
    <span><i class="pip" style="background:#00e676"></i>ready to judge</span>
    <span><i class="pip" style="background:#ffd93d"></i>questions open</span>
    <span><i class="pip" style="background:#8b8b9a"></i>context only</span>
  </div>
  {idea_cards or empty_ideas}
</div></div>
{idea_pages}

<div class="page" id="learned"><div class="wrap">
  <div class="top"><span class="brand">Top suggestions</span>
    <span class="stamp">{len(learning)} checks</span></div>
  <p class="lead" style="margin-bottom:14px">Every prediction that came due, wins
  and misses together. Showing only the wins would make this a highlight reel.</p>
  {"".join(_feed_card(e, "learned", "#00e676" if e["hit"] else "#ff6b6b") for e in learning) or empty}
</div></div>
{"".join(_learned_detail(e) for e in learning)}

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
  <a class="n-board" href="#board"><b>&#9636;</b><span>Board</span></a>
  <a class="n-ideas" href="#ideas"><b>&#10022;</b><span>Ideas</span></a>
  <a class="n-learn" href="#learned"><b>&#8599;</b><span>Top picks</span></a>
  <a class="n-miss" href="#missed"><b>&#8961;</b><span>Missed</span></a>
</nav>
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
