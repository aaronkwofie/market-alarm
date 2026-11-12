"""Turns raw market data into a 0-100 Market Safety Score and a traffic-light regime.

Six independent checks, each scored 0-100, then weighted. A check whose data
could not be fetched is dropped and the remaining weights are rescaled; if
less than 60% of the weight is available the reading is marked unreliable and
the bot will not announce a regime change on it.
"""

WEIGHTS = {
    "trend": 25,       # Are the big indexes in uptrends?
    "volatility": 20,  # Is fear (VIX) calm or spiking?
    "breadth": 20,     # Are most stocks rising, or only a few?
    "sentiment": 15,   # CNN Fear & Greed
    "credit": 10,      # Are bond investors nervous? (junk-bond spreads)
    "momentum": 10,    # Recent price action and drawdown
}

GREEN_AT, RED_BELOW = 65, 45   # score bands
MARGIN = 3                     # hysteresis so the light doesn't flicker
MIN_COVERAGE = 0.60

REGIMES = {
    "GREEN": {"label": "FAVOURABLE", "emoji": "🟢", "color": "#16a34a",
              "advice": "Conditions are healthy. Normal position sizes are reasonable; "
                        "still use stop-losses on every trade."},
    "YELLOW": {"label": "CAUTION", "emoji": "🟡", "color": "#d97706",
               "advice": "Mixed signals. Trade smaller, be selective, take profits sooner."},
    "RED": {"label": "RISK-OFF", "emoji": "🔴", "color": "#dc2626",
            "advice": "Market is under stress. Best to stay in cash or paper-trade "
                      "(e.g. on Simul8or) until the light turns green again."},
}


# ---------------------------------------------------------------- helpers
def lerp(x, x0, y0, x1, y1):
    """Linear map of x from [x0,x1] to [y0,y1], clamped."""
    if x0 == x1:
        return y1
    t = max(0.0, min(1.0, (x - x0) / (x1 - x0)))
    return y0 + t * (y1 - y0)


def piecewise(x, points):
    """points: sorted [(x, y), ...]; clamps outside the range."""
    if x <= points[0][0]:
        return points[0][1]
    for (xa, ya), (xb, yb) in zip(points, points[1:]):
        if x <= xb:
            return lerp(x, xa, ya, xb, yb)
    return points[-1][1]


def sma(values, n):
    return sum(values[-n:]) / n if len(values) >= n else None


def rsi(values, n=14):
    if len(values) < n + 1:
        return None
    gains = losses = 0.0
    for a, b in zip(values[-n - 1:-1], values[-n:]):
        d = b - a
        gains += max(d, 0)
        losses += max(-d, 0)
    if losses == 0:
        return 100.0
    rs = gains / losses
    return 100 - 100 / (1 + rs)


def _comp(name, score, details):
    return {"name": name, "score": round(max(0, min(100, score)), 1),
            "weight": WEIGHTS[name], "details": details}


# ---------------------------------------------------------------- checks
def trend(d):
    parts, details = [], []
    for sym, label in (("SPY", "S&P 500"), ("QQQ", "Nasdaq 100")):
        q = d.get(sym)
        if not q:
            continue
        c = q["closes"]
        p, s50, s200 = c[-1], sma(c, 50), sma(c, 200)
        pts = 0
        pts += 40 if p > s200 else 0
        pts += 30 if p > s50 else 0
        pts += 30 if s50 > s200 else 0
        parts.append(pts)
        details.append(
            f"{label}: {'above' if p > s50 else 'BELOW'} 50-day avg, "
            f"{'above' if p > s200 else 'BELOW'} 200-day avg"
            + ("" if s50 > s200 else " (death-cross: 50d under 200d)"))
    if not parts:
        return None
    return _comp("trend", sum(parts) / len(parts), details)


def volatility(d):
    vix = d.get("^VIX")
    if not vix:
        return None
    v = vix["price"]
    level = piecewise(v, [(12, 100), (15, 95), (20, 75), (25, 45), (30, 20), (40, 0)])
    details = [f"VIX fear gauge at {v:.1f} ({vix['change_pct']:+.1f}% on the day)"]
    v3 = d.get("^VIX3M")
    if v3:
        ratio = v / v3["price"]
        term = piecewise(ratio, [(0.85, 100), (0.95, 60), (1.0, 30), (1.08, 0)])
        score = 0.7 * level + 0.3 * term
        details.append("Short-term fear above long-term fear (stress signal)" if ratio >= 1
                       else f"VIX term structure normal (ratio {ratio:.2f})")
    else:
        score = level
    if vix["change_pct"] >= 15:
        score *= 0.7
        details.append("VIX spiking today")
    return _comp("volatility", score, details)


def breadth(d):
    b = d.get("breadth")
    if not b:
        return None
    p50 = b["above50"] / max(1, b["above50"] + b["below50"]) * 100
    p200 = b["above200"] / max(1, b["above200"] + b["below200"]) * 100
    s = 0.5 * lerp(p50, 25, 0, 70, 100) + 0.5 * lerp(p200, 25, 0, 65, 100)
    details = [f"{p50:.0f}% of US stocks above their 50-day avg, {p200:.0f}% above 200-day"]
    nh, nl = b.get("new_high", 0), b.get("new_low", 0)
    if nh + nl >= 20:
        hl = nh / (nh + nl) * 100
        s = 0.8 * s + 0.2 * hl
        details.append(f"New 52-week highs vs lows: {nh} vs {nl}")
    spy = d.get("SPY")
    if spy and spy["market_open"] and b.get("adv", 0) + b.get("dec", 0) > 2000:
        ad = b["adv"] / (b["adv"] + b["dec"]) * 100
        details.append(f"Today: {b['adv']} stocks up, {b['dec']} down")
        s = 0.85 * s + 0.15 * ad
    return _comp("breadth", s, details)


def sentiment(d):
    fg = d.get("fear_greed")
    if not fg:
        return None
    x = fg["score"]
    # Extreme greed = overheated, so safety falls off above 80.
    s = x if x <= 80 else 80 - (x - 80) * 2
    return _comp("sentiment", s, [f"CNN Fear & Greed: {x:.0f} ({fg['rating']}), "
                                  f"a week ago {fg['week_ago']:.0f}"])


def credit(d):
    parts, details = [], []
    hy = d.get("hy_spread")
    if hy:
        lvl = piecewise(hy["value"], [(3.0, 100), (4.0, 75), (5.0, 45), (6.5, 15), (8.0, 0)])
        chg = hy["value"] - hy["month_ago"]
        if chg > 0.4:
            lvl *= 0.75
        parts.append(lvl)
        details.append(f"Junk-bond spread {hy['value']:.2f}% ({chg:+.2f} vs a month ago)")
    hyg, ief = d.get("HYG"), d.get("IEF")
    if hyg and ief:
        ratio = [a / b for a, b in zip(hyg["closes"][-60:], ief["closes"][-60:])]
        r50 = sum(ratio[-50:]) / 50
        above = ratio[-1] >= r50
        parts.append(80 if above else 30)
        details.append("Junk bonds outperforming Treasuries (risk appetite healthy)" if above
                       else "Junk bonds lagging Treasuries (investors getting defensive)")
    if not parts:
        return None
    return _comp("credit", sum(parts) / len(parts), details)


def momentum(d):
    spy = d.get("SPY")
    if not spy:
        return None
    c = spy["closes"]
    dd = (c[-1] / spy["high_52w"] - 1) * 100
    s_dd = piecewise(dd, [(-20, 0), (-10, 30), (-5, 65), (-2, 90), (0, 100)])
    ret5 = (c[-1] / c[-6] - 1) * 100
    s_5 = lerp(ret5, -5, 0, 3, 100)
    r = rsi(c)
    s_rsi = 100 if r is None else piecewise(r, [(25, 20), (40, 60), (55, 100), (70, 100), (80, 60)])
    s = 0.45 * s_dd + 0.35 * s_5 + 0.2 * s_rsi
    if spy["change_pct"] <= -2:
        s *= 0.6
    details = [f"S&P 500 {dd:.1f}% from its 52-week high",
               f"5-day change {ret5:+.1f}%, "
               f"{'today' if spy['market_open'] else 'last session'} {spy['change_pct']:+.2f}%"]
    if r is not None:
        details.append(f"RSI(14) {r:.0f}" + (" (overbought)" if r > 75 else " (oversold)" if r < 30 else ""))
    return _comp("momentum", s, details)


CHECKS = (trend, volatility, breadth, sentiment, credit, momentum)


def evaluate(data):
    comps = [c for c in (f(data) for f in CHECKS) if c]
    total_w = sum(c["weight"] for c in comps)
    coverage = total_w / sum(WEIGHTS.values())
    score = sum(c["score"] * c["weight"] for c in comps) / total_w if total_w else 0.0
    return {"score": round(score, 1), "coverage": round(coverage, 2),
            "reliable": coverage >= MIN_COVERAGE, "components": comps}


def band(score):
    return "GREEN" if score >= GREEN_AT else "YELLOW" if score >= RED_BELOW else "RED"


def regime_with_hysteresis(score, prev):
    """Only leave the current regime once the score is clearly past the boundary."""
    if prev not in REGIMES:
        return band(score)
    if prev == "GREEN":
        return "GREEN" if score >= GREEN_AT - MARGIN else band(score)
    if prev == "RED":
        return "RED" if score < RED_BELOW + MARGIN else band(score)
    if score >= GREEN_AT + MARGIN:
        return "GREEN"
    if score < RED_BELOW - MARGIN:
        return "RED"
    return "YELLOW"
