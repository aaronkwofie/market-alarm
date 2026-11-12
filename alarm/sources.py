"""Live data fetchers. Every fetcher returns a dict, or raises; the caller
records failures so one broken source never stops the whole run."""

import csv
import io
import json
import re
import time
from datetime import datetime, timezone
from urllib.parse import quote

import requests

_SESSION = requests.Session()
_SESSION.headers.update({
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
})


def _get(url, retries=3, timeout=20, headers=None):
    last = None
    for attempt in range(retries):
        try:
            r = _SESSION.get(url, timeout=timeout, headers=headers)
            if r.status_code == 200 and r.content:
                return r
            last = f"HTTP {r.status_code}"
        except requests.RequestException as exc:
            last = type(exc).__name__
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"{url.split('?')[0]} failed: {last}")


# ---------------------------------------------------------------- Yahoo Finance
def yahoo(symbol):
    """One year of daily closes plus the live price.

    `closes` always ends with today's live/last price, so indicators include
    the current session."""
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol)}"
           "?range=1y&interval=1d&includePrePost=false")
    data = _get(url).json()
    res = data["chart"]["result"][0]
    meta = res["meta"]
    pairs = [(t, c) for t, c in zip(res["timestamp"], res["indicators"]["quote"][0]["close"])
             if c is not None]
    if len(pairs) < 60:
        raise RuntimeError(f"{symbol}: not enough history")
    offset = meta.get("gmtoffset", 0)

    def day(ts):
        return datetime.fromtimestamp(ts + offset, timezone.utc).date()

    price = float(meta.get("regularMarketPrice") or pairs[-1][1])
    rmt = meta.get("regularMarketTime", pairs[-1][0])
    closes = [c for _, c in pairs]
    if day(pairs[-1][0]) == day(rmt):
        closes = closes[:-1] + [price]
    else:
        closes = closes + [price]
    prev = closes[-2]

    period = (meta.get("currentTradingPeriod") or {}).get("regular") or {}
    now = time.time()
    is_open = bool(period) and period.get("start", 0) <= now < period.get("end", 0)

    return {
        "symbol": symbol,
        "price": price,
        "prev_close": prev,
        "change_pct": (price / prev - 1) * 100 if prev else 0.0,
        "closes": closes,
        "session_date": day(rmt).isoformat(),
        "market_open": is_open,
        "high_52w": max(closes[-252:]),
    }


# ---------------------------------------------------------------- Finviz
def finviz_breadth():
    """Market breadth for all NYSE/Nasdaq/AMEX stocks from the Finviz home page."""
    html = _get("https://finviz.com/").text
    bars = None
    for block in re.findall(r'<script type="application/json"[^>]*>(.*?)</script>', html, re.S):
        if "marketStatsBars" in block:
            bars = json.loads(block)["marketStatsBars"]
            break
    if not bars:
        raise RuntimeError("Finviz layout changed: breadth bars not found")
    out = {}
    for b in bars:
        label = (b.get("tooltipEmphasis") or b.get("leftTitle") or "").lower()
        pair = (int(b["leftCount"]), int(b["rightCount"]))
        if "advancing" in label:
            out["adv"], out["dec"] = pair
        elif "new high" in label:
            out["new_high"], out["new_low"] = pair
        elif "sma50" in label:
            out["above50"], out["below50"] = pair
        elif "sma200" in label:
            out["above200"], out["below200"] = pair
    if "above50" not in out or "above200" not in out:
        raise RuntimeError("Finviz layout changed: SMA breadth missing")
    return out


FINVIZ_IDEAS_URL = ("https://finviz.com/screener.ashx?v=111&f=cap_largeover,"
                    "sh_avgvol_o1000,ta_highlow52w_nh,ta_sma200_pa,ta_sma50_pa&o=-change")


def finviz_ideas(limit=10):
    """Large, liquid US stocks in a confirmed uptrend making new 52-week highs."""
    html = _get(FINVIZ_IDEAS_URL).text
    seen = []
    for t in re.findall(r"quote\.ashx\?t=([A-Z][A-Z.\-]{0,9})&", html):
        if t not in seen:
            seen.append(t)
    return {"tickers": seen[:limit], "url": FINVIZ_IDEAS_URL}


# ---------------------------------------------------------------- Sentiment
def cnn_fear_greed():
    r = _get("https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
             headers={"Referer": "https://edition.cnn.com/", "Origin": "https://edition.cnn.com"})
    fg = r.json()["fear_and_greed"]
    return {"score": float(fg["score"]), "rating": fg["rating"],
            "week_ago": float(fg.get("previous_1_week") or fg["score"])}


def crypto_fear_greed():
    d = _get("https://api.alternative.me/fng/?limit=1").json()["data"][0]
    return {"score": int(d["value"]), "rating": d["value_classification"]}


# ---------------------------------------------------------------- Credit (FRED)
def fred_series(series_id):
    # FRED stalls on browser-like User-Agents, so identify plainly.
    text = _get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}", timeout=30,
                retries=2, headers={"User-Agent": "market-alarm/1.0 (python-requests)"}).text
    rows = []
    for row in csv.reader(io.StringIO(text)):
        if len(row) == 2:
            try:
                rows.append((row[0], float(row[1])))
            except ValueError:
                continue
    if len(rows) < 25:
        raise RuntimeError(f"FRED {series_id}: not enough data")
    return {"date": rows[-1][0], "value": rows[-1][1], "month_ago": rows[-21][1]}
