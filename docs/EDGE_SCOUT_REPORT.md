# EDGE SCOUT — EXPLORATORY

Research only. This screen downloads public historical candles; it never uses a
broker token, websocket or order endpoint. Findings are hypotheses for independent
local verification, not completion of the local system's setup/validation roadmap.

## Ranked complete common out-of-sample year: 2025

Ranking is after-cost Sharpe of each family's annual rolling training selector.
Each test choice was fixed using only the preceding three calendar years. All
families share the complete 2025 test year, avoiding a comparison between decades
of daily evidence and one year of hourly evidence. 2026 is a separately labeled
partial diagnostic and is excluded from this ranking and complete-year metrics.
A high rank is not a claim that a family passes the PROMISING screen.

| Rank | Family | Variants counted | Verdict | CAGR | Max DD | Sharpe | Deflated Sharpe probability | Trades | Win % | Average hold days | Average move / cost % | Best / worst year |
|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| 1 | Gap-and-go / gap-fade | 8 | WEAK | 8.61% | -2.49% | 1.83 | 5.40% | 113 | 50.44 | 1.54 | 1.24 / 0.50 | 2025: 8.60% / 2025: 8.60% |
| 2 | Low-volatility tilt | 6 | NO EDGE | 4.56% | -9.68% | 0.50 | 0.36% | 384 | 41.67 | 105.85 | 2.20 / 2.71 | 2025: 4.55% / 2025: 4.55% |
| 3 | Cross-sectional momentum | 6 | WEAK | 9.08% | -24.98% | 0.50 | 0.25% | 110 | 59.09 | 87.71 | 15.07 / 1.04 | 2025: 9.08% / 2025: 9.08% |
| 4 | Sector relative strength | 6 | NO EDGE | -7.90% | -27.55% | -0.25 | 0.04% | 435 | 50.11 | 34.26 | 4.07 / 2.02 | 2025: -7.90% / 2025: -7.90% |
| 5 | Swing BOS/CHoCH | 8 | NO EDGE | -8.08% | -22.19% | -0.33 | 0.04% | 1157 | 35.96 | 8.43 | 1.14 / 3.32 | 2025: -8.07% / 2025: -8.07% |
| 6 | 52-week-high breakout | 8 | NO EDGE | -10.19% | -19.80% | -0.83 | 0.00% | 722 | 31.72 | 9.17 | 1.00 / 3.25 | 2025: -10.18% / 2025: -10.18% |
| 7 | Short-term mean reversion | 8 | NO EDGE | -21.51% | -25.61% | -1.33 | 0.00% | 1175 | 30.55 | 4.95 | 0.61 / 3.25 | 2025: -21.50% / 2025: -21.50% |
| 8 | Calendar effects | 10 | NO EDGE | -9.99% | -12.01% | -2.08 | 0.00% | 650 | 32.15 | 5.69 | -0.02 / 0.82 | 2025: -9.99% / 2025: -9.99% |

Trade counts are FIFO realized lot fragments, so partial exits count separately.
Win rate, holding time and move/cost averages are unweighted fragment averages.
Tiny partial lots can dominate the cost average; it is not the portfolio expense
ratio. A positive portfolio return can therefore fail the fragment-cost screen.
CAGR includes cash days; Sharpe uses daily equity returns, 252 sessions/year and
zero risk-free rate. Deflated Sharpe is a probability, not a modified ratio: all
60 registered trials count, including losing/unavailable variants. Its scale
uses cross-trial Sharpe dispersion on this same 2025 OOS period, skew/kurtosis,
and a conservative AR(1) effective-sample approximation. One year is a short
sample; this correction does not remove universe, data-quality or regime bias.

## Longer available OOS history and partial diagnostic

Only complete annual tests appear below. The daily candidate set is available
before 2025; hourly and certified pre-holiday candidates become eligible only
in 2025 because their three-year training data/calendars start in 2022. The
family selector therefore had fewer eligible variants in older folds. Periods
and candidate pools differ: this table is supporting evidence, not the common
ranking. Best/worst years here refer only to complete OOS years.
Missing selected-winner years are omitted, never replaced with another variant
or filled with zero returns. CAGR is suppressed when those years interrupt the
history; pooled valid-fold Sharpe/drawdown are not a continuous calendar account.

| Family | Complete OOS years | CAGR | Max DD | Sharpe | Trades | Best year | Worst year | 2026 partial compounded return |
|---|---|---:|---:|---:|---:|---|---|---:|
| Gap-and-go / gap-fade | 2025–2025 (1) | 8.61% | -2.49% | 1.83 | 113 | 2025: 8.60% | 2025: 8.60% | -4.38% |
| Low-volatility tilt | 2003–2025 (22); missing 2016 | — (gap) | -55.33% | 1.13 | 12111 | 2009: 104.78% | 2008: -42.99% | -11.02% |
| Cross-sectional momentum | 2003–2025 (22); missing 2015 | — (gap) | -63.43% | 1.29 | 3417 | 2007: 116.32% | 2008: -55.34% | -10.81% |
| Sector relative strength | 2004–2025 (21); missing 2015 | — (gap) | -69.38% | 0.82 | 14409 | 2009: 114.67% | 2008: -61.52% | -7.04% |
| Swing BOS/CHoCH | 2003–2025 (22); missing 2015 | — (gap) | -91.88% | 0.11 | 30749 | 2003: 164.87% | 2008: -62.10% | -14.88% |
| 52-week-high breakout | 2004–2025 (22) | -0.46% | -57.02% | 0.05 | 16637 | 2021: 37.78% | 2004: -22.25% | -12.19% |
| Short-term mean reversion | 2003–2025 (23) | 2.30% | -52.01% | 0.22 | 23090 | 2009: 97.97% | 2004: -22.56% | -25.52% |
| Calendar effects | 2003–2025 (22); missing 2015 | — (gap) | -40.00% | 0.17 | 11930 | 2003: 30.36% | 2020: -11.81% | -3.61% |

The 2026 diagnostic ends on 2026-10-01 and assumes liquidation at the final
observed open. It is not a completed one-year test. Each fold begins with INR
1,000,000 cash; normalized returns compound across independently restarted folds.
Those metrics do not represent one uninterrupted fixed-share cash account.
Terminal exits use the final open, submitted at the preceding close. No final
close or future open is used. Warmup uses only past observations. Missing final
execution prices invalidate the affected fold rather than fabricate a flat exit.

## Bull / bear / sideways OOS results — 2025

Regimes are descriptive, determined using the preceding Nifty50 close: BULL is
above its 200-session SMA and positive 63-session return; BEAR is below and
negative; other complete inputs are SIDEWAYS. Missing warmup is UNCLASSIFIED.
Each cell is conditional compounded return / Sharpe / number of daily samples.
Regime dates are noncontiguous, so no regime CAGR is claimed.

| Family | Bull | Bear | Sideways | Unclassified samples |
|---|---|---|---|---:|
| Gap-and-go / gap-fade | 5.33% / 2.57 / 144 | 2.45% / 1.35 / 68 | 0.64% / 1.28 / 35 | 0 |
| Low-volatility tilt | -0.95% / -0.16 / 144 | 1.53% / 0.53 / 68 | 3.96% / 2.18 / 35 | 0 |
| Cross-sectional momentum | 7.80% / 0.91 / 144 | -6.87% / -0.61 / 68 | 8.64% / 2.56 / 35 | 0 |
| Sector relative strength | 6.63% / 0.74 / 144 | -15.53% / -1.71 / 68 | 2.26% / 0.85 / 35 | 0 |
| Swing BOS/CHoCH | 6.05% / 0.75 / 144 | -12.67% / -1.58 / 68 | -0.73% / -0.26 / 35 | 0 |
| 52-week-high breakout | 5.35% / 0.83 / 144 | -13.82% / -4.64 / 68 | -1.07% / -0.46 / 35 | 0 |
| Short-term mean reversion | -6.04% / -0.79 / 144 | -17.97% / -2.77 / 68 | 1.85% / 0.96 / 35 | 0 |
| Calendar effects | -6.31% / -3.13 / 144 | -3.83% / -2.09 / 68 | -0.11% / -0.09 / 35 | 0 |

## Plain-words family verdicts — EXPLORATORY

The verdict rule was set before viewing returns. PROMISING requires positive
common and extended CAGR, both Sharpes at least 0.5, common deflated-Sharpe
probability at least 95%, at least 100 common realized fragments, at least three
complete extended OOS years and more than 55% positive extended years. NO EDGE
means nonpositive common CAGR or average gross move no greater than average
cost. Other cases are WEAK. These thresholds are screening choices, not a
trained classifier or an untouched final holdout.

- **Gap-and-go / gap-fade — WEAK:** The available result does not meet the evidence thresholds; positive returns alone are insufficient, especially with only one complete common test year.
- **Low-volatility tilt — NO EDGE:** The portfolio gained 4.56% after costs, but unweighted fragment move 2.20% versus cost 2.71% failed the frozen screen. Tiny partial lots can dominate that average; this does not mean the portfolio lost. Validate capital-weighted move/cost before interpreting this label.
- **Cross-sectional momentum — WEAK:** The available result does not meet the evidence thresholds; positive returns alone are insufficient, especially with only one complete common test year.
- **Sector relative strength — NO EDGE:** The common test lost after costs or its average gross move did not clear average cost. It should not receive deployment priority.
- **Swing BOS/CHoCH — NO EDGE:** The common test lost after costs or its average gross move did not clear average cost. It should not receive deployment priority.
- **52-week-high breakout — NO EDGE:** The common test lost after costs or its average gross move did not clear average cost. It should not receive deployment priority.
- **Short-term mean reversion — NO EDGE:** The common test lost after costs or its average gross move did not clear average cost. It should not receive deployment priority.
- **Calendar effects — NO EDGE:** The common test lost after costs or its average gross move did not clear average cost. It should not receive deployment priority.

## HANDOFF — top three verification candidates, EXPLORATORY

These are the three highest common-period family ranks, even if their verdict is
WEAK or NO EDGE. They are not three approved edges. For each, the exact variant
below is the **2026 training winner**, chosen on 2023–2025 data; if unavailable,
the latest completed-fold training winner is shown. No best-OOS parameter is
substituted. Run the frozen parameters on an untouched local period, using
point-in-time constituents, verified corporate actions/dividends, dated calendars
and actual contract-note costs before interpreting any apparent improvement.

Common execution: long-only integer shares; next-bar-open entry; INR1m fold
capital; 20-position limit, 10% target cap, gross exposure <=100%; calendar
constituent baskets allow50 positions. Fixed-entry families allow10 positions.
All targets/costs and training rules remain as preregistered. Keep all candidate
variants counted; do not revise parameters from these OOS outcomes.

1. **Gap-and-go / gap-fade** (WEAK): `F7_go_gap3_hold1`, `60minute`. Training interval 2023-01-01 to 2025-12-31. The ranked 2025 family result used `F7_go_gap3_hold1`; it is not attributed to a different latest recipe. Exact parameters: `{"gap": 0.03, "hold_days": 1, "side": "go"}`. Exact rule: Require the actual09:15 first regular hourly bar. Compare its open with the previous session daily close: go needs a positive gap above the threshold; fade needs a negative gap below minus the threshold. First-bar close must exceed its open. Enter next hourly open, rank largest absolute gap first, allow10names at10%, and hold declared sessions with a flat cooldown before renewal. Calendar decisions use the last known session of the month/ISOweek from dated circulars; execution always lags one bar. Full definitions remain in [EDGE_SCOUT_STRATEGIES.md](EDGE_SCOUT_STRATEGIES.md).
2. **Low-volatility tilt** (NO EDGE): `F6_vol120_top10`, `daily`. Training interval 2023-01-01 to 2025-12-31. The ranked 2025 family result used `F6_vol120_top10`; it is not attributed to a different latest recipe. Exact parameters: `{"lookback": 120, "top": 10}`. Exact rule: At the weekly decision close, rank ascending sample standard deviation(ddof1) of daily simple close returns over the declared trailing sessions. Select top names equally at1/top, capped10%; next-session-open weekly rebalance and hold shares between decisions. Calendar decisions use the last known session of the month/ISOweek from dated circulars; execution always lags one bar. Full definitions remain in [EDGE_SCOUT_STRATEGIES.md](EDGE_SCOUT_STRATEGIES.md).
3. **Cross-sectional momentum** (WEAK): `F1_m252_top20`, `daily`. Training interval 2023-01-01 to 2025-12-31. The ranked 2025 family result used `F1_m252_top10`; it is not attributed to a different latest recipe. Exact parameters: `{"lookback": 252, "skip": 21, "top": 20}`. Exact rule: At each month-end decision close, rank stocks by close[−skip]/close[−(skip+lookback)]−1. Select top names equally, cap each at10%; unfilled slots stay cash. Rebalance at the next observed session open, then hold shares until the next scheduled monthly decision. Calendar decisions use the last known session of the month/ISOweek from dated circulars; execution always lags one bar. Full definitions remain in [EDGE_SCOUT_STRATEGIES.md](EDGE_SCOUT_STRATEGIES.md).

Local verification must include capital-weighted gross move/cost and total
portfolio fee drag alongside the unweighted fragment statistics. Match the
vendor hourly grid, including its final 15:15–15:30 partial bar; a local engine
that emits only complete 60-minute bars needs an explicit conversion and matched
ablation, rather than silently dropping the final bar and claiming equivalence.

## Costs, data and limitations

- Delivery STT0.1% each side; stamp0.015% buy; SEBI0.0001% each side; GST18% on
  eligible fees; brokerage INR20 per order; sell DP INR20 per security/day plus
  GST; slippage **0.1% each side**. NSE exchange/IPFT bundle0.00332% Apr–Sep2024 and0.00307% fromOct2024
  onward (the component split changes inMar2026). BeforeApr2024 the model
  projects0.00297% exchange plus dated IPFT; it is not a verified historical invoice. Cost formula and
  authoritative sources are in [EDGE_SCOUT_ENGINE.md](EDGE_SCOUT_ENGINE.md) and
  [EDGE_SCOUT_REVIEW.md](EDGE_SCOUT_REVIEW.md). Additional contract-note
  charges are not certified by this model; IPFT is included in the dated bundle.
- Current Nifty200/Nifty50 constituents and current sector mappings are used
  throughout history: **survivorship and membership look-ahead bias**. Delisted
  and former constituents are absent. Named sector proxies are not exact historic
  industry portfolios. Some current sector-index histories are backcast before
  product launch; historical publication/membership availability is not certified.
  Historical data includes possible legacy instrument
  splices and unusual index backcasts. The after-cost statistics are conditional
  on this biased universe, not investable historical performance.
- Prices are used as served, without synthetic split/dividend adjustments.
  **Corporate-action adjustment status is UNKNOWN**; dividends/total returns are
  not established. Large changes may be market moves or actions. Local handoff
  must reconcile both prices and shares. No future-detected whole-symbol filter
  was used to conceal this issue.
- 565 distinct conflicting session rows (569 conflicting source observations)
  have missing OHLCV in the research panel; all
  source records and flags remain in raw caches. Missing observations remain
  NaN, no future filling or skipped-trade reconstruction. Missing-price orders
  retry only the original unresolved security budget; valuation uses known marks
  with stale flags. Every missing symbol-period is listed in
  [EDGE_SCOUT_MISSING.csv](EDGE_SCOUT_MISSING.csv), including empty retention/
  prelisting-unknown windows, intraperiod missing sessions and price conflicts.
- All download requests use an explicit User-Agent, no Authorization/token and
  at most5requests/sec with cached backoff retries. Empirical public GETs returned
  successfully, while official V3 examples show Bearer authorization; anonymous
  access is observed behavior, not a guaranteed future API contract. Raw payloads
  and normalized data stay under gitignored `data/edge_scout/`.
- Only regular weekday sessions are modeled. Verified2022–2026 Muhurat dates are
  excluded from regular execution; other historic special-session timing is not
  fully certified. Hourly vendor15:15 candle is only15minutes. Dated NSE annual
  holidays and amendments are replayed as of their conservative publication
  availability, with preholiday evaluation limited to certified-calendar folds.
- Gap fade is long-only recovery after a negative gap. No short cash-equity or
  derivative strategy was simulated. Calendar returns are a current equal-weight
  Nifty50 constituent basket proxy with per-stock costs, not the nontradable
  Nifty50 price index. Basket costs/capacity differ from an ETF.

## Reproduction and recorded evidence

```bash
python -m pip install -e '.[dev,research]'
python -m orderflow.research.edge_data --through 2026-10-01
python -m orderflow.research.edge_scout
python -m orderflow.research.edge_report
pytest -q
```

No keys or secrets are required. Cache hashes detect revised source/data/rules;
completed folds resume only with matching fingerprints. These public source
files can change later, so preserving the original ignored cache is required
for byte-identical reproduction. The preregistered variant ledger, per-fold
training selections and OOS metric snapshot are committed under `docs/`.

Registry SHA256: `2adaa9e6a2611cb460ac64789755ebc14130e38101402e65ec4e6af7495c6846`. Counted trials: **60**. Final screen runtime: 422.54s (cache reuse disclosed by fingerprints).

- daily dataset SHA256: `f337ec6854ec2f0921c7b0a781ba1b63bb59863b52f385fc208ff8283345a784`
- hourly dataset SHA256: `7a31e5578e3f8ae5a5abf2bbbe7919e7d7f3e9f532f0caa5fe1aa30fd00e6dcc`

Invalid folds explicitly recorded: **56**; details in `EDGE_SCOUT_INVALID_FOLDS.csv`. Data coverage/quality counts and source hashes are in [EDGE_SCOUT_DATA.md](EDGE_SCOUT_DATA.md).
