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
:root{--bg:#0a0a0f;--card:#111118;--line:#1a1a24;--teal:#00d4aa;--green:#00e676;
--purple:#7c4dff;--red:#ff6b6b;--yellow:#ffd93d;--w:#fff;--g:#8b8b9a;--lg:#b0b0c0}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
background:var(--bg);color:var(--w);-webkit-font-smoothing:antialiased;
padding:0 0 96px;line-height:1.5}
.wrap{max-width:430px;margin:0 auto;padding:0 16px}
.top{display:flex;justify-content:space-between;align-items:baseline;padding:18px 0 4px}
.brand{font-size:15px;font-weight:800;letter-spacing:-.2px}
.stamp{font-size:11px;color:var(--g)}
.card{background:var(--card);border:1.5px solid var(--line);border-radius:20px;
padding:17px;position:relative;overflow:hidden;margin-bottom:11px}
.card::before{content:'';position:absolute;inset:0 0 auto 0;height:1px;
background:linear-gradient(90deg,transparent,rgba(255,255,255,.06),transparent)}
a{color:inherit;text-decoration:none;display:block}
h1{font-size:19px;font-weight:800;letter-spacing:-.3px;margin-bottom:6px}
h2{font-size:16px;font-weight:700;margin:24px 0 11px;letter-spacing:-.2px}
h3{font-size:13.5px;font-weight:700;margin-bottom:3px}
h4{font-size:11.5px;font-weight:700;color:var(--lg);text-transform:uppercase;
letter-spacing:.7px;margin:18px 0 8px}
p{font-size:12.5px;color:var(--g)}
.lead{font-size:13px;color:var(--lg);line-height:1.6}
.row{display:flex;gap:13px;align-items:center}
.av{width:42px;height:42px;border-radius:50%;display:flex;align-items:center;
justify-content:center;font-size:14px;font-weight:800;flex-shrink:0;border:1.5px solid}
.grow{flex:1;min-width:0}
.chev{color:var(--g);font-size:19px;font-weight:300}
.badge{display:inline-block;padding:3px 10px;border-radius:20px;font-size:10px;
font-weight:700;letter-spacing:.4px}
.meter{height:6px;background:var(--line);border-radius:3px;overflow:hidden;margin:11px 0 8px}
.meter i{display:block;height:100%;border-radius:3px}
.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:13px 0}
.stat{background:var(--card);border:1.5px solid var(--line);border-radius:16px;
padding:12px 6px;text-align:center}
.stat b{display:block;font-size:15px;font-weight:800;margin-bottom:3px}
.stat span{font-size:9px;color:var(--g);text-transform:uppercase;letter-spacing:.5px}
.call{text-align:center;padding:22px 18px}
.call .sig{font-size:30px;font-weight:800;letter-spacing:-1px;margin-bottom:5px}
.call .sub{font-size:12px;color:var(--g)}
dl{display:grid;grid-template-columns:1fr auto;gap:9px 12px;font-size:12.5px}
dt{color:var(--g)}
dd{font-weight:700;text-align:right;font-variant-numeric:tabular-nums}
ul{list-style:none;font-size:12.5px;color:var(--g)}
li{padding-left:15px;position:relative;margin-bottom:7px;line-height:1.55}
li::before{content:'';position:absolute;left:0;top:8px;width:5px;height:5px;
border-radius:50%;background:var(--g)}
.back{font-size:13px;color:var(--g);font-weight:600;padding:16px 0 6px}
.note{font-size:11px;color:var(--g);line-height:1.65;padding:14px 2px}
.dot{width:9px;height:9px;border-radius:50%;flex-shrink:0}
.what{font-size:12px;color:var(--lg);line-height:1.55;margin-top:10px;
padding-top:10px;border-top:1px solid var(--line);text-align:left}
.what-sm{font-size:11.5px;color:var(--lg);line-height:1.45;margin-bottom:3px}
.times{font-size:10px;font-weight:700;color:var(--g);margin-left:5px}
.tile{display:flex;align-items:center;gap:10px;padding:11px 13px;background:var(--card);
border:1.5px solid var(--line);border-radius:14px;margin-bottom:7px}
.tile b{font-size:12.5px;font-weight:700;min-width:82px}
.tile p{font-size:11px;line-height:1.4}
.pip{width:10px;height:10px;border-radius:50%;flex-shrink:0}
.legend{display:flex;gap:14px;margin:2px 0 14px;flex-wrap:wrap}
.legend span{font-size:11px;color:var(--g);display:flex;align-items:center;gap:6px}
.legend i{width:10px;height:2.5px;border-radius:2px;display:inline-block}
.chartkey{margin:10px 0 0}
.card svg{display:block;margin:4px 0 0;overflow:visible}
.page{display:none}
.page:target{display:block}
body:has(.page:target) #home{display:none}
@supports not selector(:has(*)){.page{display:block;border-top:1px solid var(--line);
margin-top:26px;padding-top:6px}}
.nav{position:fixed;bottom:0;left:0;right:0;display:flex;justify-content:center;
gap:6px;padding:10px 0 max(18px,env(safe-area-inset-bottom));
background:linear-gradient(to top,var(--bg) 72%,transparent);z-index:50}
.nav a{display:flex;flex-direction:column;align-items:center;gap:4px;color:var(--g);
padding:5px 22px;font-size:9.5px;font-weight:600}
.nav b{font-size:16px;font-weight:800}
body:not(:has(.page:target)) .nav .n-home,
body:has(#board:target) .nav .n-board,
body:has(#charts:target) .nav .n-charts,
body:has(#ideas:target) .nav .n-ideas,
body:has(#learned:target) .nav .n-learn,
body:has(#missed:target) .nav .n-miss{color:var(--teal)}
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
    <p>{_e(m['status_line'])}</p></div>
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
  <a class="back" href="#learned">&lsaquo; What it learned</a>
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
    tiles = "".join(f"""
  <div class="tile"><span class="pip" style="background:{_e(a['colour'])}"></span>
    <b>{_e(a['symbol'])}</b>
    <div class="grow"><p style="color:{_e(a['colour'])}">{_e(a['flag_label'])}</p>
      <p>{_e(a['reason'])}</p></div></div>""" for a in b.get("assets", []))

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
                      for a in b.get("assets", []))

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
  <div class="top"><span class="brand">Sigbot</span><span class="stamp">{_e(stamp)} UTC</span></div>
  {demo_banner}
  <div class="card"><h1>{proven} of {total} proven</h1>
    <p class="lead">{_e(h['message'])}</p>
    <div class="meter"><i style="width:{(proven / max(total, 1)) * 100:.0f}%;background:var(--teal)"></i></div>
    <p>{h['observations_total']:,} predictions checked so far. Each one only counts
    once we know how it turned out.</p></div>
  <h2>What it watches</h2>
  {cards}
  <p class="note">{_e(data.get('disclaimer', ''))}</p>
</div></div>
{"".join(_model_page(m) for m in data["models"])}

<div class="page" id="board"><div class="wrap">
  <div class="top"><span class="brand">The board</span>
    <span class="stamp">{b.get("size", 0)} assets</span></div>
  <p class="lead" style="margin-bottom:10px">{_e(b.get("note", ""))}</p>
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
  <div class="top"><span class="brand">What it learned</span>
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
  <a class="n-home" href="#home"><b>&#9670;</b>Home</a>
  <a class="n-board" href="#board"><b>&#9632;</b>Board</a>
  <a class="n-charts" href="#charts"><b>&#9204;</b>Charts</a>
  <a class="n-ideas" href="#ideas"><b>&#9670;</b>Ideas</a>
  <a class="n-learn" href="#learned"><b>&#9650;</b>Learned</a>
  <a class="n-miss" href="#missed"><b>&#9679;</b>Missed</a>
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
