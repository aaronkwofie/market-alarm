# Market Alarm

A free bot that runs 24/7, checks the US stock market every 15 minutes, and e-mails you when
conditions change. It also publishes a live dashboard page.

## What it watches

| Check (weight) | Source | Asks |
|---|---|---|
| Trend (25%) | Yahoo Finance | Are the S&P 500 and Nasdaq above their 50- and 200-day averages? |
| Volatility (20%) | Yahoo Finance (VIX, VIX3M) | Is fear calm or spiking? |
| Breadth (20%) | **Finviz** home page | Are most of the ~5,600 US stocks rising, or only a few? |
| Sentiment (15%) | CNN Fear & Greed | Is the crowd panicking or overheated? |
| Credit (10%) | St. Louis Fed (FRED) + HYG/IEF | Are bond investors nervous? |
| Momentum (10%) | Yahoo Finance | How far is the S&P 500 from its high? Recent moves, RSI |

The checks combine into a **Market Safety Score from 0 to 100**:

- 🟢 **65+ FAVOURABLE**: healthy market, normal trading.
- 🟡 **45–64 CAUTION**: mixed signals, trade smaller.
- 🔴 **below 45 RISK-OFF**: market under stress, stay in cash or paper-trade.

To stop false alarms, the light only changes when the score is clearly past a boundary (3-point
margin) **and** two checks in a row agree.

When the light is not red, each e-mail also lists strong large-cap stocks from a **Finviz**
screener (uptrend plus new 52-week high). These are ideas to research, not buy signals.

## E-mails it sends

| When | E-mail |
|---|---|
| Light changes colour | 🟢/🟡/🔴 "Conditions changed" (the main alarm) |
| S&P 500 falls 1.5% or 3% in a day, rises 2%, or VIX jumps 15% or goes over 30 | Intraday warning, at most once per day each |
| Weekdays, about 1.5 hours before the US open | Morning brief |
| Weekdays, after the US close | Close summary |
| Sunday evening | Weekly outlook |
| Data sources down for an hour | A warning that alerts are paused |

Times in e-mails are Ghana time (GMT). The US session is 14:30–21:00 Ghana time
(13:30–20:00 from March to early November).

## Setup (about 15 minutes, free)

### 1. Make a Gmail address for the bot to send from

You can use an existing Gmail, but a separate one like `yourname.marketbot@gmail.com` is cleaner.

1. Turn on **2-Step Verification**: <https://myaccount.google.com/security>
2. Create an **App password**: <https://myaccount.google.com/apppasswords>
   (name it "Market Alarm"). Copy the 16-letter password. This is not the normal Gmail password.

### 2. Put the code on GitHub

1. Create a free account at <https://github.com> if you don't have one.
2. Create a **new public repository** called `market-alarm`. It must be public: public repos get
   unlimited free automation minutes. Your password and e-mail stay hidden in Secrets (step 3).
3. Upload everything in this folder, including the hidden `.github` folder. The easiest way is to
   run these commands in this folder:

   ```bash
   git init -b main
   git add .
   git commit -m "Market Alarm"
   git remote add origin https://github.com/YOUR-USERNAME/market-alarm.git
   git push -u origin main
   ```

### 3. Add the secrets

In the repo go to **Settings → Secrets and variables → Actions → New repository secret** and
add these three:

| Name | Value |
|---|---|
| `SMTP_USER` | the bot Gmail address from step 1 |
| `SMTP_PASS` | the 16-letter app password |
| `ALERT_TO` | `aaronamihere14@gmail.com` (add more addresses separated by commas) |

### 4. Turn on the dashboard and automation

1. **Settings → Pages → Build and deployment → Source: GitHub Actions**.
2. **Settings → Actions → General → Workflow permissions: Read and write permissions** → Save.
3. Go to the **Actions** tab, enable workflows if asked, open **Market Alarm**, click
   **Run workflow**, tick **Send a test e-mail**, and run it. A test e-mail should arrive within
   a minute or two (check Spam the first time and mark it "Not spam").
4. Click **Run workflow** again without the tick. This sends the "Market Alarm is now active"
   e-mail. After that it runs on its own.

The live dashboard is at `https://YOUR-USERNAME.github.io/market-alarm/`. Save it to the phone
home screen.

## Good to know

- **Timing:** GitHub's own scheduler proved unreliable for this repo (gaps of 5–8 hours), so a
  free **cron-job.org** job ("Market Alarm trigger") POSTs to
  `https://api.github.com/repos/aaronkwofie/market-alarm/actions/workflows/market-alarm.yml/dispatches`
  every 15 minutes with body `{"ref":"main"}` and headers `Accept: application/vnd.github+json`,
  `Content-Type: application/json` and `Authorization: Bearer <token>`. The token is a fine-grained
  GitHub token named `market-alarm-cron` (this repo only, Actions read/write) that **expires on
  13 Nov 2027**: before then, create a new one and paste it into the cron-job.org job. The GitHub
  schedule stays on as a backup.
- **Keeping it alive:** GitHub pauses scheduled jobs in repos with no activity for 60 days. The bot
  saves its state back to the repo about once an hour, which counts as activity. If it ever pauses,
  GitHub e-mails the owner and it can be re-enabled from the Actions tab.
- **Simul8or** has no data feed to read, so it is not a source. It fits well alongside the bot:
  practise every alert there with fake money for a few weeks before using real money.
- **Run on a PC instead:** `pip install -r requirements.txt`, set the same three values as
  environment variables, then run `python -m alarm` on a timer. `DRY_RUN=1` saves e-mails to
  `out/emails/` instead of sending them.
- **Tests:** `python -m tests.test_logic` runs the alert logic against simulated markets (crash,
  recovery, failed e-mail, data outage).
- **Tuning:** weights and score bands are at the top of `alarm/scoring.py`. Alert triggers are
  in `SHOCKS` in `alarm/__main__.py`.

## Important

This tool reads public market data and applies fixed rules. **It is not financial advice and
cannot guarantee any trade is safe.** Markets can fall even when every indicator looks good.
Always use stop-losses, never risk money you cannot afford to lose, and learn on a simulator first.
