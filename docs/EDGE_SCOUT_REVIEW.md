# EDGE SCOUT independent methods review — EXPLORATORY

Reviewed on 2026-10-02. This is public-candle research, with no orders, websocket,
tokens, or credential use. Downloaded prices, current index membership and the
resulting strategy comparisons cannot certify a deployable edge.

## Verified cost sources and explicit assumptions

The [Upstox published charge schedule](https://upstox.com/brokerage-charges/)
states equity-delivery brokerage “₹20 per executed order”, STT “0.1% on buy &
sell”, delivery stamp duty “0.015% ... on buy side”, SEBI charges “₹10/crore”,
and DP charges “₹20.0 per scrip per day only on sell”. GST is 18% on the
brokerage, exchange/demat and applicable fee components. The published page
includes several dated schedules; its newer table supersedes older tables:

| Fee | Source fact / research treatment |
|---|---|
| STT | 0.1% of consideration on each delivery side; also explicitly required by the user. |
| Stamp duty | 0.015% on buys only. |
| NSE exchange charge | 0.00322% from 2024-04-01 through 2024-09-30; 0.00297% from 2024-10-01 through 2026-02-28. The official component becomes ₹306.99/crore from 2026-03-01. Older-period projection must be identified as an assumption. |
| NSE IPFT | ₹10/crore each side from 2023-04-01 through 2026-02-28; ₹0.01/crore before that interval and again from 2026-03-01. The total exchange/IPFT bundle is 0.00332% in April–September 2024 and 0.00307% from October 2024 onward, charged once plus GST. |
| SEBI | ₹10/crore = 0.0001% of consideration on both sides. |
| Brokerage | Current published flat ₹20 per executed delivery order. Projecting the current tariff backward is a research assumption. |
| DP | Current published ₹20 per security per sell day, before applicable GST. Multiple partial exits for that security on the same date must not multiply this charge. |
| GST | 18% on applicable service charges, not on STT or stamp duty. |
| Slippage | User-mandated 0.1%; treating it as 0.1% on **each** side is the conservative explicit scout assumption. It is not a measured historical execution cost. |

The [NSE statutory levies page](https://www.nseindia.com/invest/first-time-investor-sebi-turnover-fees-stt-other-levies)
independently confirms delivery-equity STT “0.100 per cent” on purchase and sale,
delivery stamp duty 0.015% payable by the buyer, SEBI 0.0001%, and stockbroker
service GST 18%. Both sources were retrieved using an explicit research
User-Agent. The fixed DP and brokerage charges make initial capital and position
size material assumptions; percentage-only round-trip cost is insufficient.
Applying the requested delivery schedule to a same-day exit is deliberately
conservative and is not an assertion about the actual intraday tariff.

The official [NSE/FA/73061 circular](https://nsearchives.nseindia.com/content/circulars/FA73061.pdf),
dated 2026-02-27, states that the existing cash-market ₹297 exchange plus ₹10
IPFT per crore per side becomes ₹306.99 exchange plus ₹0.01 IPFT from March 1.
The total remains ₹307: adding another ₹10 to the current 0.00307% bundle would
double-count IPFT. Conversely, omitting the separate ₹10 before March 2026 would
understate costs. [NSE/FA/56129](https://nsearchives.nseindia.com/content/circulars/FA56129.pdf),
dated 2023-03-24, verifies the April 1, 2023 increase from ₹0.01 to ₹10 per crore.
[NSE/FA/64232](https://nsearchives.nseindia.com/content/circulars/FA64232.pdf),
dated 2024-09-27, confirms the uniform October 2024 exchange schedule;
[NSE/FA/61137](https://nsearchives.nseindia.com/content/circulars/FA61137.pdf),
dated 2024-03-14, supplies the preceding broker-volume slabs. Source PDFs and
their checksum manifest are cached in ignored `data/edge_scout/review_sources/`.

## Public data and adjustment status

[Upstox Historical Candle Data V3 documentation](https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/)
lists daily availability from January 2000 and minute/hour availability from
January 2022, with a decade maximum per daily request and a quarter maximum per
hour request. Some observed public responses extend further back; those are
as-served histories, not proof that the instrument was investable then. Nifty 50
history observed before index launch must be treated as historical/backcast
reference data, never a stock position.

The documentation's example requests include a Bearer header. The download agent
separately verified HTTP 200 **without** Authorization on public daily and hourly
requests. That empirical access result permits this scout and does not promise
permanent unauthenticated availability. Authentication failure must remain a
missing-data record; no token fallback is authorized.

No corporate-action adjustment guarantee was found on the official V3 candle
page. Adjustment status is **UNCERTIFIED**. As-served OHLCV is retained; no invented
split factors or dividend reinvestment is applied. Large discontinuities can flag
possible splits, demergers, bonuses, data errors or genuine moves, but cannot
identify which occurred. They can corrupt rankings, swing signals, volatility,
gaps, portfolio valuation and reported returns. Local verification must use a
validated corporate-action ledger and a point-in-time membership history before
any family can be considered confirmed. Missing dividends also mean price-return
results are not shareholder total returns.

## Calendar evidence

The official NSE website uses the year-filtered public endpoint
`https://www.nseindia.com/api/holiday-master?type=trading&year=YYYY`, verified for
2022–2026. The `CM` segment is the equity calendar. The API mixes holidays with
special live trading records and omits some Muhurat dates. It contains no
announcement/revision timestamps. Consequently, a final calendar snapshot cannot
automatically serve as a point-in-time pre-holiday signal source.

The second source is the dated capital-market trading circular itself, located
through the official NSE circular-search endpoint. Annual calendars were verified
as published in the previous year: CMTR50560 (2022), CMTR54757 (2023), CMTR59722
(2024), CMTR65587 (2025), CMTR71775 (2026). Dated changes must supersede the annual
announcement only after publication. Do not infer holidays from future gaps in
the downloaded Nifty price series. Muhurat sessions and announced exceptional
Saturday sessions require separate treatment from normal NSE delivery sessions.

## Review gates

- Freeze and count all registered variants before results, including variants that
  cannot be tested. Family selection uses only each three-year training block.
  One-year test returns and later ranking never feed parameter selection.
- Targets use completed candles and confirmed right-hand swings, execute at the
  following available bar open, and record actual close availability. Daily
  bar-start timestamps alone are not valid signal-availability timestamps.
- Maintain integer-share cash accounting with fees and slippage; no borrowing,
  shorting, invented price fills, or index positions. The calendar basket requires
  its explicit 50-position cap rather than silently truncating 50 names to 20.
- Missing bars remain missing, cannot silently shorten held time, and cannot create
  an executable open. Unclosed positions and stale marks need audit counts.
- Report after-cost metrics only from concatenated unseen test blocks, and report
  limited years/regimes honestly. Partial final test years are not full walk-forward
  folds. Training-derived variant choice and an OOS-ranked candidate handoff are
  exploratory selection, not a subsequent independent holdout.
- DSR is a probability, not an annualized Sharpe ratio. All 60 registered trials
  count; its effective-sample and expected-max approximation must be disclosed.
  Correlated variants, serially correlated returns and current-universe survival
  bias remain limitations after that numerical correction.

## Implementation findings and dispositions

The initial engine review identified stale DP pricing, an omitted dated exchange
fee interval, and order audit timestamps that used bar starts as signal
availability. The engine agent corrected these and added exact-answer checks:
DP ₹20 with GST once per sell security/day, the three verified NSE tariff
intervals above, and completed-bar availability before next-open execution.
Missing-order retries now preserve successful fills: only the missing security's
original intended budget is retried, with its original signal availability. A
dedicated regression confirms that a successfully filled security is not
rebalanced when a different security later recovers its open. A later fee-source
correction includes the verified IPFT bundle once. The final engine checkpoint
passed 16 exact-answer tests.

The initial runner review identified mismatched hourly timeframe keys, stale
pre-holiday parameter names, a holiday JSON reader incompatible with the dated
event format, and omission of `CONFLICTING_DUPLICATE_CANDLE` quality flags.
Those findings were corrected before the final full study: daily execution
timestamps use 09:15 IST, hourly keys match the registry, calendar events are
passed to chronological replay, and conflicting source observations become NaN
rather than arbitrarily selecting one candle. The loader separately excludes
known Muhurat special sessions from regular-session execution. Comparing Nifty
50's observed daily sessions against the verified final regular-session calendar
found no missing whole regular weekday from January 2022 through October 1, 2026.

The strategy agent added chronological calendar-event replay and regressions
showing that the original June 2023 Bakri-ID holiday signal remains intact after
the later announced holiday shift, that the January 2024 exceptional holiday
cannot generate an earlier signal, and that day-end announcement availability
and hourly bar-end availability are respected. The exact source events and
checksums are in [EDGE_SCOUT_HOLIDAYS.json](EDGE_SCOUT_HOLIDAYS.json); source PDFs
and ZIPs are cached under ignored `data/edge_scout/review_sources/`. Annual weekday
holiday counts are 13, 15, 14, 14 and 15 for 2022–2026 before later revisions.

The training selector reads only the preceding three-year training summaries,
requires at least 30 realized FIFO fragments, chooses maximum after-cost Sharpe,
and resolves ties by variant ID. All declared variants remain counted for DSR.
The coordinating agent identified and corrected an initial candidate-pool filter
that depended on whether a candidate's later OOS fold was executable. The final
selector chooses the training winner first; an invalid OOS winner invalidates
that family fold, with no substitute. The initial review missed that pool filter;
the final source and known-answer regression enforce the correct selection order.
The runner's preceding-close anchor permits a flat test portfolio to adopt the
already available target at the first test open; accounting starts flat rather
than importing training positions. Causal feature warmup remains allowed.

Common-window comparisons must identify 2025 as the complete one-year OOS fold.
Any 2026-through-October-1 evaluation is a **partial forward diagnostic**, not a
completed one-year test, and must disclose its artificial endpoint liquidation.
The handoff is selected after viewing OOS results and therefore needs a new,
untouched local validation period. Calendar training and evaluation use verified
2022–2026 announcement history; years before 2022 lack certified announced
calendars and cannot establish a pre-holiday edge.

An independent engine/strategy checkpoint passed 90 tests before the subsequent
calendar and retry regressions. This count is a checkpoint, not the final full
repository test total or validation of the study's eventual numerical results.

## Final study audit

The final committed snapshot records all 60 variants as EVALUATED, eight valid
complete 2025 family results, and 56 explicitly recorded invalid candidate/family
folds. The report's common-period numerical table matches the snapshot, including
the exact Sharpe ordering when two displayed values both round to 0.50. All
deflated-Sharpe probabilities fail the 95% screening threshold; no family is
PROMISING. The hourly gap family also has only one complete OOS year and cannot
satisfy the declared three-year evidence threshold yet.

The three handoff variants match the **2026 training-only winners**, using
2023–2025 training returns: `F7_go_gap3_hold1`, `F6_vol120_top10` and
`F1_m252_top20`. These are verification priorities, not three established edges.
Their 2026 diagnostic is already observed; local confirmation requires a new
untouched period, not another retrospective run on that same diagnostic.

Extended OOS histories have a missing 2015 for momentum, structure, sector
relative strength and calendar effects, and a missing 2016 for low volatility.
Their raw span-based CAGR skips an unknown year; it must not be interpreted as
continuous investable performance. The readable report should suppress that
CAGR and identify the omitted years, while retaining the raw snapshot for audit.
Drawdowns on retained-fold returns likewise do not cover the missing year's risk.

Low volatility gained approximately 4.55% after costs in 2025. Its NO EDGE verdict
comes from the preregistered **unweighted FIFO-fragment** move/cost screen, not
from a portfolio loss: average move 2.20% versus cost 2.71%. Small partial lots
can dominate those unweighted averages. They are not a volume-weighted round-trip
cost estimate. Local verification should reconcile aggregate rupee costs and
notional-weighted moves against actual contract notes, alongside untouched
portfolio returns. Changing the frozen screen after inspecting results would
be a new research choice and must be counted accordingly.
