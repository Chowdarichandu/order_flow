Screen eight strategy families using public historical NSE candles, causal
next-bar-open execution and delivery costs. The EXPLORATORY report evaluates
all 60 frozen variants with rolling three-year training/one-year testing; no
broker token, websocket or order endpoint is involved.

Complete 2025 is the common OOS comparison. Gap strategies returned +8.61%
CAGR, momentum +9.08% and low volatility +4.56%, but **no family passes the
PROMISING screen** after the 60-trial Sharpe correction and evidence thresholds.
Low volatility fails the unweighted fragment-cost test despite its positive
portfolio result; that is explained explicitly. All eight partial-2026 results
are negative. The report hands off the top three ranks for independent local
verification with exact training-selected rules, not deployment approval.

The public download completed 5,139 successful requests: 200 current equities,
Nifty50 and 13 sector proxies; 946,598 daily and 1,656,534 hourly rows. Every
request sets User-Agent, throttles and caches; 9,807 missing/quality audit records
are committed. Raw candles remain gitignored. Current constituents create
survivorship/membership look-ahead bias; corporate-action adjustment is unknown,
some legacy/index histories are spliced/backcast, and early fee assumptions are
projected. These limitations prevent an investable historical claim.

Five selected-family years are unavailable; extended CAGR is suppressed for
those discontinuous histories. All 56 invalid fold records are retained without
substituting winners using test availability. Terminal exits are previous-close
instructions executed at final open. The 15:15 hourly vendor bar is a partial
15-minute interval and must be reconciled with the local bar builder.

Review: `docs/EDGE_SCOUT_REPORT.md`, `EDGE_SCOUT_REVIEW.md`, data/engine/strategy
definitions and committed variant, fold-selection, results and missing ledgers.
This is a separate research task; it does not mark T15–T17 complete.

Validation: **152 offline tests and 92 subtests pass**, including known-answer
cash/fees, causal availability, truncation, confirmed swings, dated holidays,
missing-price retries, invalid-fold selection and simulated HTTP edge cases.
Four subagents implemented and independently reviewed the study. Full final
screen runtime: **422.54 seconds**, with cache reuse controlled by source/data
fingerprints. This is a candle-research benchmark, not websocket throughput.

Reproduce after preserving the recorded raw cache:

```bash
python -m pip install -e '.[dev,research]'
python -m orderflow.research.edge_data --through 2026-10-01
python -m orderflow.research.edge_scout
python -m orderflow.research.edge_report
pytest -q
```

| Module | Tests | Status | Open issues |
|---|---|---|---|
| Public downloader/cache/audit | 19 | DONE | Survivorship, unknown adjustments, missing histories |
| Execution/costs/OOS metrics | 16 | DONE | Projected early tariffs and unverified live capacity |
| Eight strategy families / 60 variants | 79 + 92 subtests | DONE | No PROMISING family; capital-weighted cost verification required |
| Walk-forward/report integration | 8 | DONE | 56 disclosed invalid fold records; five selected-family year gaps |
| Existing simulator/scaffold | 30 | GREEN | Local system roadmap remains separate |
