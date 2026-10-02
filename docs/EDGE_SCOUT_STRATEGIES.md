# EXPLORATORY strategy preregistration

This is a research screen, with no order API, websocket or token. The registry
`config/edge_scout_variants.json` was written before observing backtest results.
All **60 variants** count as trials, including unavailable variants and losing
variants. There is no expansion, deletion or tuning in response to test returns.
A family winner is selected on each training window, never on its next test year.
The following are deliberate research definitions, not claims that the existing
local zone/setup roadmap is complete.

Every signal is available at the observed bar close; execution is the following
observed bar's **open**. Daily bars use the session close. The final hourly candle
can cover only 15:15–15:30 IST and is a partial interval, not a fabricated hour.
Index instruments supply reference data only and never become positions.
Missing inputs are unavailable and never filled with future observations.

Ranked portfolios select top 10 or 20 and assign 1/top weight, capped at 10% per
name. Ranking ties use the stable alphabetic panel-symbol order. Unfilled slots
remain cash. Monthly and weekly portfolios rebalance only on their scheduled
calendar decision dates, including when the selected names are unchanged.
Individual-entry portfolios have at most 10 positions at 10% each; ties in entry
ranking use stable symbol order. Expiry or a bearish structure break creates at
least one flat close decision before a fresh entry, ensuring exits are actually
charged costs. Portfolio limits and fees are applied by the execution engine.

| Family | Count | Exact frozen variants and rule |
|---|---:|---|
| 1 Cross-sectional momentum | 6 | Close 21 observations ago / close (21+63/126/252) observations ago − 1; rank top 10/20. Decide on last known trading session of each calendar month; next-session-open rebalance. 21 sessions approximates one month, 252 one year. |
| 2 52-week-high breakout | 8 | Close strictly above highest **prior** 252 session highs; volume at least 1.25/1.5× mean **prior** 20 session volume; close above current trailing 100/200-session simple moving average. Hold 5/10 sessions. Rank simultaneous entries by fractional breakout. |
| 3 Oversold uptrend reversion | 8 | Wilder RSI(2) strictly below 5/10 while close is above trailing 100/200-session SMA. Hold 2/5 sessions. Rank entries by lowest RSI. Wilder RSI seeds mean gains/losses from the first two consecutive finite changes, then recursive Wilder smoothing; flat changes give RSI50. |
| 4 Swing BOS/CHoCH | 8 | Daily and hourly strict fractals with 2/3 left and right bars. A swing is usable only after all right confirmation bars close; tied highs/lows are not swings. Close crosses above latest confirmed swing high (bullish BOS or bullish CHoCH) from at/below it. Daily hold 5/10 sessions; hourly hold 1/3 sessions. Exit at next open following a close crossing below latest confirmed swing low or expiry. Rank simultaneous entries by last-bar return. No FVG or disputed zone rule is used. |
| 5 Sector relative strength | 6 | Stock 20/60/120-session simple return minus its mapped sector price-index return over the same window; top 10/20, weekly rebalance. A missing sector reference makes that stock unavailable. Index constituents and sector mappings are current, not historical. |
| 6 Low-volatility tilt | 6 | Lowest sample standard deviation (ddof1) of daily simple close returns over trailing 20/60/120 sessions; top 10/20, weekly rebalance. No forward volatility estimate. |
| 7 Gap go/fade | 8 | Hourly first regular 09:15 candle open vs prior session DAILY close (or observed prior session final 15:15 partial-candle close). Gap strictly above +2/+3% for go, strictly below −2/−3% for fade; first candle close must exceed its open. Decide only after that first candle closes and enter the next hourly open. Hold 1/2 sessions. Long-only: this does not test short gap fades. Missing opening bar or previous session close makes signal unavailable. |
| 8 Calendar basket | 10 | Current Nifty50 constituents equal weight, capped at 10% each; a **survivorship-biased basket proxy**, not investment in the nontradable index. Turn-of-month exposure last b sessions of month plus first a sessions of next month, (b,a)=(1,1),(1,2),(2,2),(0,2),(3,1); close decision on session before exposure, so next-open execution matches the declared dates. Pre-holiday exposure starts the last session before a supplied announced weekday holiday, holds 1/2/3/4/5 sessions. Its decision is two sessions before that holiday, avoiding buying only after the holiday. |

Weekly decisions occur at the close of the last known trading session of the ISO
calendar week, using weekends plus supplied holiday dates. Monthly/calendar
windows similarly use announced calendar information, not the final price
sample's future missing-session pattern. `holiday_events` are replayed only
when their `available_at_assumption` is at or before that daily/hourly decision
close; when event history is supplied, static final holiday sets are ignored.
Date-only official circulars are conservatively available at 23:59:59 IST on
their publication day. The June2023 Bakri holiday amendment preserves the
June26 signal for the originally announced June28 holiday; its late June27
publication cannot retroactively create or erase an earlier decision. The
late-announced January22,2024 closure cannot create a January18 decision. **Pre-holiday variants are not testable
without a verified announced holiday calendar.** They remain counted trials.

The current-constituent Nifty200/Nifty50 universe, sector assignments, historical
coverage differences, unknown vendor corporate-action adjustments, index return rather than
stock total-return data, and the approximation of calendar months by trading
sessions must appear as report limitations. Basket fees include per-stock
sell-side DP costs; price-index exposures cannot be substituted to lower costs.
All reported findings and any top-three handoff remain **EXPLORATORY**.
