# EXPLORATORY execution and metrics conventions

This research module never connects to a broker. It consumes public historical
OHLCV arrays, uses vectorized targets/sizing and a stateful order-accounting loop,
and records hypothetical cash-equity fills. Its conclusions require independent
local verification. Historical daily/hourly bars cannot establish order flow.

## Causal execution and folds

A daily signal is available at 15:30 Asia/Kolkata; an hourly signal is available
at its bar end, capped at 15:30. The public timestamps are bar starts. The engine
executes at the following observed grid row's open, and raises if that open
predates signal availability. This assumes the next open is obtainable with the
specified slippage; actual computation latency and market-impact capacity remain
unverified. OHLC array inputs are never filled to fabricate a trade.

Targets are nonnegative weights. A changed target triggers a rebalance; a
scheduled mask supports monthly/weekly rebalancing even if the selected names
are unchanged. An entire NaN target row explicitly means HOLD. A missing open
prevents execution and is counted; each unresolved security retains its intended budget from the scheduled open
and is retried on a later observed open without using a future close. Already
executed securities are never rebalanced because another name is missing. A
new scheduled decision supersedes outstanding intents. Retry orders retain
the original signal availability timestamp; cash-limited partial buy remainders
are canceled until the next scheduled decision. Missing closing marks use only a
current open or last known mark, and stale observations are counted.

Portfolios begin each fold with INR 1,000,000 cash, zero positions and integer
shares. Default maximums are 20 positions and 10% target weight per name; the
calendar basket may explicitly use 50 positions. Only instruments marked
tradable can be bought; index OHLC are reference inputs. Ties among equal
weights are resolved by stable symbol order and truncations are reported.
Sells precede buys, brokerage/costs are deducted immediately, and affordable
integer quantities are solved without borrowing. Weights are capped and total
target exposure is normalized to at most 100%.

A fold's terminal liquidation is submitted at the preceding bar close and
executes at its last open. It does not use the last close or any future bar.
An unavailable final open or a sell whose fees exceed cash plus proceeds leaves outstanding shares, reported explicitly;
that fold must not be silently treated as flat. Evaluation returns must be
concatenated only across complete, independently restarted OOS folds, with all
entry/exit costs included. The rolling helper uses half-open calendar intervals
of three years training and one year testing; an incomplete final test year is
omitted. Feature warmup precedes a fold, but position/accounting state does not.

## Delivery cost model

The frozen default model uses:

| Component | Buy | Sell |
|---|---:|---:|
| STT | 0.1% | 0.1% |
| Stamp duty | 0.015% | — |
| NSE exchange/IPFT bundle | 0.00332% April–September 2024; 0.00307% October 2024 onward | Same |
| SEBI | 0.0001% | 0.0001% |
| Brokerage | INR 20 per executed order | INR 20 per executed order |
| DP | — | INR 20 per security per IST day |
| GST | 18% of brokerage, exchange/IPFT and SEBI | 18% of brokerage, exchange/IPFT, SEBI and DP |
| Slippage | +0.1% to observed open | −0.1% from observed open |

The current public brokerage source is <https://upstox.com/brokerage-charges/>.
NSE circular [FA73061](https://nsearchives.nseindia.com/content/circulars/FA73061.pdf)
(27 February 2026) verifies that the preceding INR 297 exchange plus INR 10
IPFT per crore per side becomes INR 306.99 plus INR 0.01 from 1 March 2026;
the total stays INR 307. The engine includes that bundle once, plus GST.
[FA56129](https://nsearchives.nseindia.com/content/circulars/FA56129.pdf)
(24 March 2023) verifies the IPFT increase from INR 0.01 to INR 10 per crore
from 1 April 2023. The 0.00322% exchange rate is documented for April–September
2024; adding IPFT gives 0.00332%. The 0.00297% exchange rate is documented for
October 2024–February 2026; adding IPFT gives 0.00307%.

Before April 2024, applying the 0.00297% exchange rate is a **research projection**,
not a historical tariff claim. The dated IPFT component is 0.000000001 before
April 2023 and 0.000001 from April 2023 through February 2026. The March 2026
0.0000307 rate already includes IPFT. Explicit custom `exchange` rates are
constant all-in exchange/IPFT projections, so the engine adds no automatic
IPFT to them. Calling the fee helper without a timestamp uses the explicit
base rate without dated IPFT; actual engine orders always supply a timestamp.
Fees are frozen configurable research assumptions; additional contract-note
charges may remain unmodeled, so this does not guarantee a live invoice. DP
applies once even if a security has several sell orders that day.
The user prescribed delivery STT and 0.1% slippage; applying that delivery model
to gap strategies is conservative and does not reproduce an intraday tariff.

Slippage is charged on each side, rather than assuming 0.1% total round trip.
Realized total cost includes buy/sell statutory and broker charges plus the
price differences created by slippage. Entry fee allocation follows FIFO lots;
partial exits are realized lot fragments, and the reported trade count uses
that explicit definition. Gross moves compare unslipped entry/exit opens.
Hold duration is elapsed calendar days. Average move/cost and win rate are
unweighted averages of realized fragments, with that limitation disclosed.

## Metrics and multiplicity

Hourly equity is sampled once per IST date. Both daily and hourly families use
252 sessions for annualized Sharpe, with zero risk-free rate. CAGR uses elapsed
calendar time, including cash days, and maximum drawdown includes initial
capital as the first watermark. Best/worst years are compounded calendar-year
returns; any partial year must be labeled in the report.

Deflated Sharpe is a **probability**, not an adjusted Sharpe ratio. The engine
implements the Bailey/Lopez de Prado expected-maximum-Sharpe correction for the
entire preregistered trial count. It estimates skew and kurtosis of evaluated
daily returns and uses the conservative AR(1) effective-sample approximation
`N_eff = N × (1 − max(rho1,0)) / (1 + max(rho1,0))`, bounded to [3,N]. This is an
approximation, not a proof that strategy returns are independent. A supplied
cross-trial annualized Sharpe standard deviation is converted to daily scale;
without it, the explicit sampling-null fallback is `1/sqrt(N_eff−1)`. With fewer
than 30 daily observations or zero return variance, the probability is missing.
All registered variants count even when they fail or produce zero trades.

Regimes use only the preceding available Nifty close: BULL means above its
200-session average and positive 63-session return; BEAR requires below and
negative; otherwise complete inputs are SIDEWAYS. Warmup/missing inputs are
UNCLASSIFIED. Regime results report conditional compounded return, Sharpe,
drawdown and observation count. They omit CAGR because those dates are
noncontiguous. Regime assignment is descriptive and does not filter trades.

## Validation

`tests/test_edge_engine.py` contains exact cash/next-open/terminal accounting,
explicit delivery-fee and March 2026 tariff answers, no-negative-cash integer
orders, index exclusion, position caps, missing/open/close audit, prefix
truncation, monthly-mask/HOLD semantics, DP once per security/day, causal signal
availability, disjoint three-plus-one-year folds, known move/win/drawdown,
trial-count Sharpe penalty, and causal benchmark regime classification.
