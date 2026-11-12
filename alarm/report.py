"""HTML for the alert e-mails and the live dashboard page."""

from datetime import datetime, timedelta
from html import escape
from zoneinfo import ZoneInfo

from .scoring import GREEN_AT, RED_BELOW, REGIMES

ET = ZoneInfo("America/New_York")
GH = ZoneInfo("Africa/Accra")

NAMES = {"trend": "Trend", "volatility": "Volatility (fear)", "breadth": "Market breadth",
         "sentiment": "Sentiment", "credit": "Credit / bonds", "momentum": "Momentum"}

TICKERS = [("SPY", "S&P 500 (SPY)"), ("QQQ", "Nasdaq 100 (QQQ)"), ("IWM", "Small caps (IWM)"),
           ("^VIX", "VIX fear index"), ("BTC-USD", "Bitcoin")]


def us_session_in_ghana(now_utc):
    d = now_utc.astimezone(ET).date()
    o = datetime(d.year, d.month, d.day, 9, 30, tzinfo=ET).astimezone(GH)
    c = datetime(d.year, d.month, d.day, 16, 0, tzinfo=ET).astimezone(GH)
    return f"{o:%H:%M}–{c:%H:%M} Ghana time"


def _bar_color(score):
    return "#16a34a" if score >= GREEN_AT else "#d97706" if score >= RED_BELOW else "#dc2626"


def _numbers_rows(data):
    rows = []
    for sym, label in TICKERS:
        q = data.get(sym)
        if not q:
            continue
        chg = q["change_pct"]
        col = "#16a34a" if chg >= 0 else "#dc2626"
        if sym == "^VIX":   # rising VIX is bad
            col = "#dc2626" if chg >= 0 else "#16a34a"
        price = f"{q['price']:,.0f}" if q["price"] > 1000 else f"{q['price']:,.2f}"
        rows.append((label, price, f'<span style="color:{col}">{chg:+.2f}%</span>'))
    fg = data.get("fear_greed")
    if fg:
        rows.append(("CNN Fear &amp; Greed", f"{fg['score']:.0f}", escape(fg["rating"].title())))
    cfg = data.get("crypto_fg")
    if cfg:
        rows.append(("Crypto Fear &amp; Greed", str(cfg["score"]), escape(cfg["rating"])))
    return rows


def email_html(ev, data, events, now_utc):
    """ev: output of scoring.evaluate plus 'regime'. events: list of (title, text)."""
    reg = REGIMES[ev["regime"]]
    gh_time = now_utc.astimezone(GH)
    spy = data.get("SPY")
    status = ("US market is OPEN" if spy and spy["market_open"] else "US market is CLOSED")

    ev_html = "".join(
        f'<tr><td style="padding:10px 14px;border-left:4px solid {reg["color"]};background:#f8fafc">'
        f'<b>{escape(t)}</b><br><span style="color:#334155">{escape(x)}</span></td></tr>'
        f'<tr><td style="height:8px"></td></tr>' for t, x in events)

    comp_html = ""
    for c in ev["components"]:
        comp_html += (
            f'<tr><td style="padding:8px 0 2px;font-weight:600">{NAMES[c["name"]]}</td>'
            f'<td style="padding:8px 0 2px;text-align:right;font-weight:600;color:{_bar_color(c["score"])}">'
            f'{c["score"]:.0f}/100</td></tr>'
            f'<tr><td colspan="2" style="padding:0 0 4px"><div style="background:#e2e8f0;height:6px;border-radius:3px">'
            f'<div style="background:{_bar_color(c["score"])};height:6px;border-radius:3px;width:{c["score"]:.0f}%"></div></div></td></tr>'
            f'<tr><td colspan="2" style="color:#475569;font-size:13px;padding-bottom:6px">'
            + "<br>".join(escape(x) for x in c["details"]) + "</td></tr>")

    num_html = "".join(
        f'<tr><td style="padding:5px 0;border-bottom:1px solid #e2e8f0">{a}</td>'
        f'<td style="padding:5px 0;border-bottom:1px solid #e2e8f0;text-align:right">{b}</td>'
        f'<td style="padding:5px 0;border-bottom:1px solid #e2e8f0;text-align:right;width:90px">{c}</td></tr>'
        for a, b, c in _numbers_rows(data))

    ideas_html = ""
    ideas = data.get("ideas")
    if ideas and ideas["tickers"] and ev["regime"] != "RED":
        links = " · ".join(
            f'<a href="https://finviz.com/quote.ashx?t={escape(t)}" style="color:#2563eb;text-decoration:none">{escape(t)}</a>'
            for t in ideas["tickers"])
        ideas_html = (
            '<h3 style="margin:24px 0 6px;font-size:16px">Stocks showing strength today</h3>'
            f'<p style="margin:0 0 6px;font-size:15px">{links}</p>'
            '<p style="margin:0;color:#64748b;font-size:12px">Large, liquid US stocks above their 50- and 200-day '
            'averages making new 52-week highs (Finviz screener). Ideas to research or practise with on '
            'Simul8or, not buy recommendations.</p>')

    unreliable = "" if ev["reliable"] else (
        '<p style="background:#fef3c7;padding:10px;border-radius:6px;font-size:13px">Some data sources '
        f'did not respond, so this reading uses only {ev["coverage"]*100:.0f}% of the usual inputs.</p>')

    dash = data.get("dashboard_url")
    dash_html = (f'<p style="text-align:center;margin:22px 0"><a href="{escape(dash)}" style="background:#0f172a;'
                 'color:#fff;padding:10px 18px;border-radius:6px;text-decoration:none">Open live dashboard</a></p>'
                 if dash else "")

    return f"""<!doctype html><html><body style="margin:0;background:#f1f5f9;font-family:Segoe UI,Arial,sans-serif;color:#0f172a">
<table width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:20px 10px">
<table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#fff;border-radius:10px;overflow:hidden">
<tr><td style="background:{reg['color']};color:#fff;padding:22px 24px">
<div style="font-size:13px;opacity:.9">MARKET ALARM · {gh_time:%a %d %b %Y, %H:%M} Ghana time</div>
<div style="font-size:28px;font-weight:700;margin-top:6px">{reg['emoji']} {reg['label']}</div>
<div style="font-size:18px;margin-top:4px">Market Safety Score: <b>{ev['score']:.0f}/100</b></div>
</td></tr>
<tr><td style="padding:20px 24px">
<p style="margin:0 0 14px;font-size:15px"><b>What this means:</b> {escape(reg['advice'])}</p>
<p style="margin:0 0 16px;color:#475569;font-size:13px">{status}. Regular US session: {us_session_in_ghana(now_utc)}.</p>
{unreliable}
<table width="100%" cellpadding="0" cellspacing="0">{ev_html}</table>
<h3 style="margin:18px 0 6px;font-size:16px">Key numbers</h3>
<table width="100%" cellpadding="0" cellspacing="0" style="font-size:14px">{num_html}</table>
<h3 style="margin:24px 0 6px;font-size:16px">Why the score is {ev['score']:.0f}</h3>
<table width="100%" cellpadding="0" cellspacing="0" style="font-size:14px">{comp_html}</table>
{ideas_html}
{dash_html}
<p style="margin:24px 0 0;color:#94a3b8;font-size:11px;line-height:1.5">Score bands: 65+ favourable, 45–64 caution,
below 45 risk-off. Data: Finviz, Yahoo Finance, CNN Fear &amp; Greed, St. Louis Fed (FRED), alternative.me.
This is an automated market-conditions monitor, not financial advice. No signal is ever 100% safe:
always use stop-losses and never risk money you cannot afford to lose.</p>
</td></tr></table></td></tr></table></body></html>"""


def _history_svg(history, now_utc):
    pts = []
    cutoff = now_utc - timedelta(days=30)
    for h in history:
        t = datetime.fromisoformat(h["t"])
        if t >= cutoff:
            pts.append((t, h["s"]))
    if len(pts) < 2:
        return '<p class="muted">The 30-day history chart fills in as the bot runs.</p>'
    W, H = 720, 200
    t0, t1 = pts[0][0].timestamp(), pts[-1][0].timestamp()
    span = max(1, t1 - t0)

    def xy(t, s):
        return (t.timestamp() - t0) / span * W, H - s / 100 * H

    path = " ".join(f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}" for i, (x, y) in enumerate(xy(t, s) for t, s in pts))
    yg, yr = H - GREEN_AT / 100 * H, H - RED_BELOW / 100 * H
    return f"""<svg viewBox="0 0 {W} {H}" preserveAspectRatio="none" class="hist" role="img" aria-label="Safety score, last 30 days">
<rect x="0" y="0" width="{W}" height="{yg}" fill="var(--g)" opacity=".10"/>
<rect x="0" y="{yg}" width="{W}" height="{yr - yg}" fill="var(--y)" opacity=".10"/>
<rect x="0" y="{yr}" width="{W}" height="{H - yr}" fill="var(--r)" opacity=".10"/>
<path d="{path}" fill="none" stroke="var(--fg)" stroke-width="2" vector-effect="non-scaling-stroke"/></svg>
<div class="muted small">{pts[0][0].astimezone(GH):%d %b} → {pts[-1][0].astimezone(GH):%d %b %H:%M} (Ghana time)</div>"""


def dashboard_html(ev, data, history, now_utc):
    reg = REGIMES[ev["regime"]]
    spy = data.get("SPY")
    status = "OPEN" if spy and spy["market_open"] else "CLOSED"
    comps = "".join(
        f'<div class="comp"><div class="row"><b>{NAMES[c["name"]]}</b>'
        f'<b style="color:{_bar_color(c["score"])}">{c["score"]:.0f}</b></div>'
        f'<div class="bar"><span style="width:{c["score"]:.0f}%;background:{_bar_color(c["score"])}"></span></div>'
        f'<div class="muted small">{"<br>".join(escape(x) for x in c["details"])}</div></div>'
        for c in ev["components"])
    nums = "".join(f"<tr><td>{a}</td><td class='r'>{b}</td><td class='r'>{c}</td></tr>"
                   for a, b, c in _numbers_rows(data))
    ideas = data.get("ideas")
    ideas_html = ""
    if ideas and ideas["tickers"]:
        ideas_html = ("<section><h2>Strong stocks today (Finviz)</h2><p>" + " · ".join(
            f'<a href="https://finviz.com/quote.ashx?t={escape(t)}" target="_blank" rel="noopener">{escape(t)}</a>'
            for t in ideas["tickers"]) + '</p><p class="muted small">Large caps in uptrends at new 52-week highs. '
            "Research ideas only, not recommendations.</p></section>")
    errors = data.get("errors") or []
    err_html = (f'<p class="muted small">Sources unavailable this run: {escape(", ".join(errors))}</p>'
                if errors else "")
    if not ev["reliable"]:
        err_html = ('<p style="background:#fef3c7;color:#78350f;padding:10px;border-radius:8px">Most data sources '
                    'did not respond on this run, so the score below is not reliable. The light shows the last '
                    'confirmed reading.</p>') + err_html
    gh = now_utc.astimezone(GH)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="300">
<title>Market Alarm</title>
<style>
:root{{--bg:#f1f5f9;--card:#fff;--fg:#0f172a;--muted:#64748b;--line:#e2e8f0;--g:#16a34a;--y:#d97706;--r:#dc2626}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0b1220;--card:#131c2e;--fg:#e2e8f0;--muted:#94a3b8;--line:#24324a}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 Segoe UI,system-ui,Arial,sans-serif}}
main{{max-width:900px;margin:0 auto;padding:16px}}
.hero{{background:{reg['color']};color:#fff;border-radius:14px;padding:22px}}
.hero .big{{font-size:34px;font-weight:700}}.hero .score{{font-size:20px}}
section{{background:var(--card);border-radius:12px;padding:16px 18px;margin-top:14px;border:1px solid var(--line)}}
h2{{font-size:17px;margin:0 0 10px}}.muted{{color:var(--muted)}}.small{{font-size:13px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:12px}}
.comp .row{{display:flex;justify-content:space-between}}.bar{{height:7px;background:var(--line);border-radius:4px;margin:4px 0 6px}}
.bar span{{display:block;height:7px;border-radius:4px}}table{{width:100%;border-collapse:collapse}}
td{{padding:6px 0;border-bottom:1px solid var(--line)}}.r{{text-align:right}}a{{color:#3b82f6}}
.hist{{width:100%;height:200px;display:block}}
</style></head><body><main>
<div class="hero"><div class="small">Updated {gh:%a %d %b %Y, %H:%M} Ghana time · US market {status} ({us_session_in_ghana(now_utc)})</div>
<div class="big">{reg['emoji']} {reg['label']}</div>
<div class="score">Market Safety Score <b>{ev['score']:.0f}</b>/100</div>
<div style="margin-top:8px">{escape(reg['advice'])}</div></div>
<section><h2>Score history (30 days)</h2>{_history_svg(history, now_utc)}</section>
<section><h2>Key numbers</h2><table>{nums}</table></section>
<section><h2>What's driving the score</h2><div class="grid">{comps}</div>{err_html}</section>
{ideas_html}
<p class="muted small" style="margin:16px 4px">65+ favourable · 45–64 caution · below 45 risk-off. Automated
monitor using Finviz, Yahoo Finance, CNN Fear &amp; Greed, FRED and alternative.me. Not financial advice;
no market is ever 100% safe. Page refreshes every 5 minutes.</p>
</main></body></html>"""
