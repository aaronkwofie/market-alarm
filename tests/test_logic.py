"""Offline tests of the alert logic with fake market data.  Run:  python -m tests.test_logic"""

import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import alarm.__main__ as m
from alarm import scoring

SENT = []


def fake_quote(price, chg=0.0, trend_up=True, is_open=True, date="2026-11-12"):
    base = [price * (0.7 + 0.3 * i / 250) if trend_up else price * (1.3 - 0.3 * i / 250) for i in range(251)]
    prev = price / (1 + chg / 100)
    closes = base[:-2] + [prev, price]
    return {"symbol": "X", "price": price, "prev_close": prev, "change_pct": chg, "closes": closes,
            "session_date": date, "market_open": is_open, "high_52w": max(closes)}


def market(good=True, spy_chg=0.3, vix=14.0, vix_chg=0.0, is_open=True):
    d = {
        "SPY": fake_quote(600, spy_chg, good, is_open), "QQQ": fake_quote(500, 0, good, is_open),
        "IWM": fake_quote(220, 0, good, is_open), "^VIX": fake_quote(vix, vix_chg, True, is_open),
        "^VIX3M": fake_quote(vix * (1.15 if good else 0.85), 0, True, is_open),
        "HYG": fake_quote(80, 0, good), "IEF": fake_quote(95, 0, not good),
        "breadth": ({"above50": 4000, "below50": 1500, "above200": 3800, "below200": 1700, "new_high": 300,
                     "new_low": 40, "adv": 3500, "dec": 1800} if good else
                    {"above50": 900, "below50": 4600, "above200": 1200, "below200": 4300, "new_high": 10,
                     "new_low": 400, "adv": 900, "dec": 4400}),
        "fear_greed": {"score": 65 if good else 12, "rating": "greed" if good else "extreme fear",
                       "week_ago": 60},
        "crypto_fg": {"score": 50, "rating": "Neutral"},
        "hy_spread": {"date": "x", "value": 3.0 if good else 6.8, "month_ago": 3.0 if good else 5.5},
        "ideas": {"tickers": ["AAPL", "MSFT"], "url": ""},
        "errors": [],
    }
    return d


def run_with(data, when, deliver=True):
    m.fetch_all = lambda: data
    m.notify.send = lambda subject, html: (SENT.append(subject), deliver)[1]
    SENT.clear()
    m.run(now=when)
    return list(SENT)


def utc(h, mi=0, day=12):
    return datetime(2026, 11, day, h, mi, tzinfo=timezone.utc)


def main():
    tmp = tempfile.mkdtemp()
    os.chdir(tmp)
    try:
        assert scoring.evaluate(market(True))["score"] >= 65, scoring.evaluate(market(True))
        assert scoring.evaluate(market(False))["score"] < 45, scoring.evaluate(market(False))
        assert scoring.regime_with_hysteresis(63, "GREEN") == "GREEN"
        assert scoring.regime_with_hysteresis(66, "YELLOW") == "YELLOW"
        assert scoring.regime_with_hysteresis(68, "YELLOW") == "GREEN"
        assert scoring.regime_with_hysteresis(47, "RED") == "RED"

        # 1) first run (06:00 ET, before morning window) -> welcome mail
        s = run_with(market(True, is_open=False), utc(11))
        assert len(s) == 1 and "now active" in s[0] and "FAVOURABLE" in s[0], s
        # 2) same conditions -> silence
        assert run_with(market(True, is_open=False), utc(11, 15)) == []
        # 3) morning window 08:30-11:00 ET (= 13:30 UTC in November) -> brief, exactly once
        assert any("Morning brief" in x for x in run_with(market(True, is_open=False), utc(13, 37)))
        assert run_with(market(True, is_open=False), utc(13, 52)) == []
        # 4) crash: first bad reading is only a candidate, but shock alerts fire
        s = run_with(market(False, spy_chg=-3.4, vix=34, vix_chg=40), utc(15, 7))
        assert len(s) == 1 and "down more than 3%" in s[0] and "FAVOURABLE" in s[0], s
        # 5) second bad reading confirms -> regime change; shocks not repeated
        s = run_with(market(False, spy_chg=-3.6, vix=35, vix_chg=42), utc(15, 22))
        assert len(s) == 1 and "Conditions changed" in s[0] and "RISK-OFF" in s[0], s
        # 6) failed delivery is retried on the next run
        s = run_with(market(False, spy_chg=-1.0, vix=35, vix_chg=5, is_open=False), utc(21, 22), deliver=False)
        assert any("close summary" in x for x in s), s
        s = run_with(market(False, spy_chg=-1.0, vix=35, vix_chg=5, is_open=False), utc(21, 37))
        assert any("close summary" in x for x in s), s
        assert run_with(market(False, is_open=False), utc(21, 52)) == []
        # 7) recovery needs two confirming readings
        assert run_with(market(True, is_open=False), utc(23)) == []
        s = run_with(market(True, is_open=False), utc(23, 15))
        assert "Conditions changed" in s[0] and "FAVOURABLE" in s[0], s
        # 8) data outage: alert once after 4 failed runs, regime unchanged
        dead = {"errors": ["all"], "ideas": None}
        for i in range(5):
            s = run_with(dead, utc(1, 7 + i * 10, day=13))
        state = m.load_state()
        assert state["regime"] == "GREEN"
        assert any("datafail" in k for k in state["sent"]), state["sent"]
        assert Path("site/index.html").exists()
        print("ALL TESTS PASSED")
    finally:
        os.chdir(Path(__file__).resolve().parents[1])
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
