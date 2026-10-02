# Roadmap

 Task       Depends   Builds                                          Done when

                      Scaffold: AGENTS.md (section 1 verbatim),
                      docs from sections 0-4, pyproject [dev],
 T00        -                                                         pytest green
                      src/orderflow/, schema.py,
                      config/default.yaml with every parameter

                      Simulators: V3 protobuf feed (trend,
                      range, gaps, resets, out-of-order,              Round-trip and edge-
 T01        T00
                      disconnect, 403, expired token, index           case tests
                      instruments) and candle history; decoders

                                                                      Expired/missing/401/403
                      auth (OAuth, daily refresh to token file),
 T02        T01                                                       tests; User-Agent
                      preflight (hard/soft, retries 08:30-09:10)
                                                                      always set

                                                                      Simulated 6-hour
                      Feed client + recorder (queue, batched
                                                                      session, zero drops,
 T03        T01       writer, crash-safe, lag/drop metrics, quality
                                                                      receive loop never
                      report), stocks + indices + VIX
                                                                      blocked

                      trades + bars (volume, aggressor,
 T04        T01                                                       Known-answer tests
                      confidence; 1/5/15/60m and volume bars)
                 History downloader (Historical Candle V3
                 1-min from 2022, resumable, throttled,      Simulator-backed tests;
T05   T01        User-Agent, gap manifest, bhavcopy          importer round-trip
                 cross-check) + importer for existing raw
                 recordings into this repo's schema

                 Order flow core: footprint, delta, CVD,     Known-answer +
T06   T04
                 diagonal/stacked imbalances                 truncation tests

                 Depth: depth imbalance, OFI, multi-level
T07   T04                                                    Known-answer tests
                 OFI, book sweeps, iceberg

                 Flow events: absorption, exhaustion,        Known-answer tests;
T08   T06
                 divergence, VPIN, Kyle's lambda             confirmation timing

                 Volume profile: session, developing,        Known-answer +
T09   T04
                 composite 5/20, naked POC, HVN/LVN, IB      truncation tests

                 VWAP: session + bands, anchored VWAPs,      Known-answer +
T10   T04
                 weekly/monthly, VWAP events                 truncation tests

                 SMC: swings, structure, BOS/CHoCH,          Known-answer tests per
T11   T04        displacement, OB, FVG, pools, sweeps,       structure; confirmation
                 premium/discount, MTF bias                  timing

                 Levels: prior day/week, opening ranges,
T12   T04                                                    Known-answer tests
                 gaps

                 Context: index regime, VIX regime, sector
T13   T03, T04   RS, breadth, time of day, liquidity tier,   Known-answer tests
                 event flags

                                                             Clustering, freshness
T14   T09-T12    Zone engine
                                                             and invalidation tests

                                                             Each setup triggers on a
      T08,       Setups S1-S5, trade plans, cost gate,
T15                                                          crafted scenario and not
      T13, T14   sizing
                                                             on its near-miss

                 Engine: one live/replay path, per-minute
                                                             Deterministic replay; live
T16   T15        point-in-time output, events and setup
                                                             simulation equals replay
                 tables

                 Research: history-tier backtester (purged   End-to-end on

T17   T16        walk-forward, costs), event study, shadow   simulated data with
                        ledger, edge board, variant ledger            report templates

                        Ops: systemd units/timers (refresh 03:45,
                        preflight 08:30, recorder 09:00-15:35,
           T02,                                                       Install dry-run on a
  T18                   history nightly), holiday calendar, Discord
           T03, T05                                                   clean container
                        alerts, status board, RUNBOOK.md, install
                        script

                        Read-only live view: per symbol, zones,
                                                                      Renders from replay
  T19      T16          VWAP bands, profile, footprint/CVD, recent
                                                                      output
                        events and setups


Parallel groups: [T02, T03, T04, T05] after T01; [T06, T07, T09, T10, T11, T12] after T04;
[T08, T13] next; then T14 -> T15 -> T16 -> [T17, T18, T19].
Deploy early: after T02 + T03 + T18, the owner installs the recorder so live data starts
accumulating while the layers are built.

## Execution status

T00 is DONE as of 2026-10-02: all 10 tests pass, including Arrow contracts.
The owner authorized package installation; the official V3 classes are available
from Upstox SDK 2.30.0. T01 is READY, not implemented. Later tasks remain NOT
STARTED pending their dependencies. No benchmark measurement is claimed.
See [resolved T00 evidence](stuck/T00.md). Empty package directories remain
scaffolding only.

| Task | Depends | Modules | Tests | 50-symbol simulated-day benchmark | Status |
|---|---|---|---|---|---|
| T00 | — | Scaffold, docs, config, schema | 10 pytest tests pass | N/A: scaffold; simulator begins at T01 | DONE |
| T01 | T00 | V3 feed/history simulators, decode | Not run; eligible next | Not run: T01 not implemented | READY |
| T02 | T01 | OAuth/token refresh, preflight | Not run; T01 pending | Not run: T01 unavailable | NOT STARTED |
| T03 | T01 | Feed/queue/Parquet recorder, quality | Not run; T01 pending | Not run: T01 unavailable | NOT STARTED |
| T04 | T01 | Trades, time/volume bars | Not run; T01 pending | Not run: T01 unavailable | NOT STARTED |
| T05 | T01 | History downloader, bhavcopy, importer | Not run; T01 pending | Not run: T01 unavailable | NOT STARTED |
| T06 | T04 | Footprint/delta/CVD/imbalances | Not run; T04 pending | Not run: T01 unavailable | NOT STARTED |
| T07 | T04 | Depth/OFI/sweeps/iceberg | Not run; T04 pending | Not run: T01 unavailable | NOT STARTED |
| T08 | T06 | Flow events/VPIN/Kyle | Not run; T06 pending | Not run: T01 unavailable | NOT STARTED |
| T09 | T04 | Profiles/naked POC/IB | Not run; T04 pending | Not run: T01 unavailable | NOT STARTED |
| T10 | T04 | VWAP/bands/anchors/events | Not run; T04 pending | Not run: T01 unavailable | NOT STARTED |
| T11 | T04 | SMC structures/pools/sweeps | Not run; T04 pending | Not run: T01 unavailable | NOT STARTED |
| T12 | T04 | Prior levels/opening ranges/gaps | Not run; T04 pending | Not run: T01 unavailable | NOT STARTED |
| T13 | T03, T04 | Index/VIX/RS/breadth/context | Not run; T03/T04 pending | Not run: T01 unavailable | NOT STARTED |
| T14 | T09–T12 | Zone engine | Not run; T09–T12 pending | Not run: T01 unavailable | NOT STARTED |
| T15 | T08, T13, T14 | S1–S5/plans/cost gate/sizing | Not run; dependencies pending | Not run: T01 unavailable | NOT STARTED |
| T16 | T15 | Unified live/replay engine | Not run; T15 pending | Not run: T01 unavailable | NOT STARTED |
| T17 | T16 | Backtest/event study/shadow/edge board | Not run; T16 pending | Not run: T01 unavailable | NOT STARTED |
| T18 | T02, T03, T05 | Ops/install/systemd/runbook | Not run; dependencies pending | Not run: T01 unavailable | NOT STARTED |
| T19 | T16 | Read-only live view | Not run; T16 pending | Not run: T01 unavailable | NOT STARTED |

Requested priority on resume: T01 → T02/T03/T05 → T18 → T04 → T06–T13 in
dependency order → T14 → T15 → T16 → T17/T19.

PR publication is also STUCK: Git and connector writes both returned HTTP 403.
See [publication evidence](stuck/PUBLISH.md). Commits are preserved locally.
