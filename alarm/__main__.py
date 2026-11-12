"""One monitoring pass: fetch data, score it, decide which alerts to send,
update the dashboard and the saved state. Run every ~15 minutes.

    python -m alarm               normal run
    python -m alarm --test-email  send one test e-mail with the current reading
"""

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import notify, report, scoring, sources

STATE_FILE = Path("data/state.json")
SITE_DIR = Path("site")

YAHOO = ["SPY", "QQQ", "IWM", "^VIX", "^VIX3M", "HYG", "IEF", "BTC-USD"]

# Intraday shock alerts: key, test, title. Each fires at most once per session.
SHOCKS = [
    ("spy_drop_3", lambda d: d["SPY"]["change_pct"] <= -3.0, "S&P 500 down more than 3% today"),
    ("spy_drop_15", lambda d: d["SPY"]["change_pct"] <= -1.5, "S&P 500 down more than 1.5% today"),
    ("spy_rally_2", lambda d: d["SPY"]["change_pct"] >= 2.0, "S&P 500 up more than 2% today"),
    ("vix_spike", lambda d: d["^VIX"]["change_pct"] >= 15, "Fear index (VIX) jumped over 15% today"),
    ("vix_30", lambda d: d["^VIX"]["price"] >= 30, "Fear index (VIX) above 30: high stress"),
]


def fetch_all():
    jobs = {s: (sources.yahoo, s) for s in YAHOO}
    jobs.update({
        "breadth": (sources.finviz_breadth,),
        "ideas": (sources.finviz_ideas,),
        "fear_greed": (sources.cnn_fear_greed,),
        "crypto_fg": (sources.crypto_fear_greed,),
        "hy_spread": (sources.fred_series, "BAMLH0A0HYM2"),
    })
    data, errors = {}, []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {k: pool.submit(f, *args) for k, (f, *args) in jobs.items()}
        for k, fut in futures.items():
            try:
                data[k] = fut.result()
            except Exception as exc:  # noqa: BLE001 - any source failure is non-fatal
                errors.append(k)
                print(f"[source failed] {k}: {exc}")
    data["errors"] = errors
    return data


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def run(test_email=False, now=None):
    for stream in (sys.stdout, sys.stderr):   # emoji-safe logs on Windows consoles
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass
    now =now or datetime.now(timezone.utc).replace(microsecond=0)
    now_et = now.astimezone(report.ET)
    today_et = now_et.date().isoformat()

    data = fetch_all()
    data["dashboard_url"] = os.environ.get("DASHBOARD_URL", "").strip()
    ev = scoring.evaluate(data)
    state = load_state()
    sent = state.setdefault("sent", {})
    prev = state.get("regime")
    events = []        # (priority, title, text)

    # ---- regime: hysteresis + must be seen on 2 consecutive runs
    regime = prev or scoring.band(ev["score"])
    if ev["reliable"]:
        state["bad_runs"] = 0
        cand = scoring.regime_with_hysteresis(ev["score"], prev)
        if prev is None:
            state["regime"] = regime = cand
            events.append((0, "Market Alarm is now active",
                           f"Monitoring has started. Current conditions: {scoring.REGIMES[cand]['label']}. "
                           "You will get an e-mail whenever conditions change, plus a brief before the US open "
                           "and a summary after the close."))
        elif cand != prev:
            if state.get("candidate") == cand:
                state["regime"] = regime = cand
                state.pop("candidate", None)
                up = list(scoring.REGIMES).index(cand) < list(scoring.REGIMES).index(prev)
                events.append((0, f"Conditions changed: {scoring.REGIMES[prev]['label']} → "
                                  f"{scoring.REGIMES[cand]['label']}",
                               ("The market has improved. " if up else "The market has deteriorated. ")
                               + scoring.REGIMES[cand]["advice"]))
            else:
                state["candidate"] = cand
                print(f"[pending] {prev} -> {cand}, waiting for confirmation next run")
        else:
            state.pop("candidate", None)
    else:
        state["bad_runs"] = state.get("bad_runs", 0) + 1
    ev["regime"] = regime

    # ---- intraday shocks (only while the US market is open)
    spy, vix = data.get("SPY"), data.get("^VIX")
    if spy and vix and spy["market_open"]:
        for key, test, title in SHOCKS:
            k = f"{key}:{spy['session_date']}"
            if k not in sent and test(data):
                events.append((1, title, f"S&P 500 {spy['change_pct']:+.2f}% · VIX {vix['price']:.1f} "
                                         f"({vix['change_pct']:+.1f}%). Be careful opening new positions."))
                sent[k] = None   # placeholder, confirmed after sending
                if key == "spy_drop_3":   # don't send the smaller drop alert too
                    sent.setdefault(f"spy_drop_15:{spy['session_date']}", None)

    # ---- scheduled briefs (US Eastern time windows, weekdays)
    hm = now_et.hour * 60 + now_et.minute
    weekday = now_et.weekday() < 5
    if weekday and 8 * 60 + 30 <= hm < 11 * 60 and f"morning:{today_et}" not in sent:
        events.append((2, "Morning brief", "Here is where the market stands before/around today's US open."))
        sent[f"morning:{today_et}"] = None
    if (weekday and hm >= 16 * 60 + 15 and spy and spy["session_date"] == today_et
            and f"close:{today_et}" not in sent):
        events.append((3, "Market close summary", f"The S&P 500 closed {spy['change_pct']:+.2f}% today."))
        sent[f"close:{today_et}"] = None
    if now_et.weekday() == 6 and hm >= 18 * 60:
        wk = f"weekly:{now_et.isocalendar()[0]}-W{now_et.isocalendar()[1]}"
        if wk not in sent:
            events.append((4, "Weekly outlook", "Conditions going into the new trading week."))
            sent[wk] = None

    # ---- data-feed problem
    if state.get("bad_runs", 0) >= 4 and f"datafail:{today_et}" not in sent:
        events.append((5, "Data sources not responding",
                       f"Failed this run: {', '.join(data['errors'])}. Alerts are paused until data returns."))
        sent[f"datafail:{today_et}"] = None

    if test_email:
        events = [(0, "Test e-mail", "If you can read this, Market Alarm e-mail delivery works.")]

    # ---- send one combined e-mail
    new_keys = [k for k, v in sent.items() if v is None]
    if events:
        events.sort(key=lambda e: e[0])
        reg = scoring.REGIMES[regime]
        subject = f"{reg['emoji']} {events[0][1]} | {reg['label']} · score {ev['score']:.0f}"
        html = report.email_html(ev, data, [(t, x) for _, t, x in events], now)
        ok = notify.send(subject, html)
        for k in new_keys:
            if ok:
                sent[k] = now.isoformat()
            else:
                sent.pop(k)          # retry on the next run
        if not ok and any(p == 0 for p, *_ in events) and not test_email:
            # keep announcing the change until it is delivered
            if prev is None:
                state.pop("regime", None)
            elif regime != prev:
                state["regime"], state["candidate"] = prev, regime
    for k in [k for k, v in sent.items() if v is None]:
        sent.pop(k)

    # ---- prune + history (one point per ~hour, or on regime change)
    cutoff = (now - timedelta(days=14)).isoformat()
    state["sent"] = {k: v for k, v in sent.items() if v and v >= cutoff}
    hist = state.setdefault("history", [])
    last_t = datetime.fromisoformat(hist[-1]["t"]) if hist else None
    if ev["reliable"] and (not hist or now - last_t >= timedelta(minutes=55) or hist[-1]["r"] != regime):
        hist.append({"t": now.isoformat(), "s": ev["score"], "r": regime})
        del hist[:-1500]
    if not test_email:
        save_state(state)

    # ---- dashboard
    SITE_DIR.mkdir(exist_ok=True)
    (SITE_DIR / "index.html").write_text(report.dashboard_html(ev, data, hist, now), encoding="utf-8")
    public = {"updated": now.isoformat(), "score": ev["score"], "regime": regime,
              "reliable": ev["reliable"], "components": ev["components"], "errors": data["errors"]}
    (SITE_DIR / "status.json").write_text(json.dumps(public, indent=1), encoding="utf-8")

    print(f"[{now:%Y-%m-%d %H:%M} UTC] score={ev['score']} regime={regime} "
          f"coverage={ev['coverage']:.0%} events={[t for _, t, _ in events]}")
    return 0


if __name__ == "__main__":
    sys.exit(run(test_email="--test-email" in sys.argv))
