# EDGE SCOUT — EXPLORATORY, DONE

Owner-authorized public-data research, separate from T00–T19. Completed on
2026-10-02 using four subagents for data, execution, strategies and independent
method review. Nothing places orders, opens a websocket or reads broker tokens.

| Component | Modules | Offline tests | Evidence / benchmark | Status | Open issues |
|---|---|---|---|---|---|
| Public data | `research/edge_data.py` | 19 | 5,139 successful public requests; 946,598 daily and 1,656,534 hourly rows | DONE | Current-survivor universe; adjustment status unknown; 9,807 missing/quality audit records |
| Execution and metrics | `research/edge_engine.py` | 16 | Dated delivery fees, causal next-open accounting, exact cash/FIFO tests | DONE | Historical fees partly projected; live capacity unverified |
| Eight families | `research/edge_strategies.py`, variant registry | 79 | 60 frozen variants, at most 10 per family; 92 parametrized subtests | DONE | No family passes PROMISING; fragment-cost averages need capital-weighted local verification |
| Walk-forward and report | `research/edge_scout.py`, `edge_report.py`, `edge_types.py` | 8 | Full final screen 422.54 s; 168 family selections; all 60 variants evaluated | DONE | 56 invalid fold records disclosed; five selected-family years unavailable |
| Independent audit | `EDGE_SCOUT_REVIEW.md`, dated holiday evidence | Included in above | Official fee/calendar sources and final metric/recipe checks | DONE | Corporate actions, point-in-time constituents, special historic sessions remain uncertified |

Full offline suite: **152 tests passed, 92 subtests passed** (30 existing tests
plus 122 EDGE SCOUT tests). No test was removed or weakened. No STUCK task;
unavailable folds remain explicit research exclusions, not repaired returns.
This candle-only study does not claim a websocket tick-throughput benchmark;
the recorded 422.54 s is the actual complete study runtime with fingerprinted
cache reuse, not a simulated 50-symbol live-feed throughput figure.

Primary comparison is the complete common 2025 OOS year, trained only on
2022–2024. Older daily folds have different candidate availability and five
missing selected-family years, so discontinuous extended CAGR is suppressed.
Partial 2026 is reported separately and is negative for all eight families.

Highest-ranked verification candidates: gap-go 3%/one session, low-volatility
120 sessions/top10, and momentum 252 sessions ending 21 sessions ago/top20.
These are 2026 **training-only winners**, not recipes chosen for highest OOS
returns. Low volatility is NO EDGE under the frozen fragment-cost screen despite
positive 2025 portfolio returns. Gap and momentum are WEAK. No approved edge.

See [report](../EDGE_SCOUT_REPORT.md), [data audit](../EDGE_SCOUT_DATA.md),
[review](../EDGE_SCOUT_REVIEW.md), [registry](../../config/edge_scout_variants.json)
and the committed results/selection/missing-period ledgers. Raw data stays in
gitignored `data/edge_scout/`; preserved cache hashes are required for exact
reproduction because public files may later change.
