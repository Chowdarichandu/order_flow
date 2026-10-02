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

T00 and T01 are DONE as of 2026-10-02. All 30 tests pass; T01's official V3
feed/history simulators and decoders are implemented, with the six-hour
50-stock benchmark recorded. T02/T03/T04/T05 are eligible next. Later tasks
await their dependencies. See [simulator evidence](SIMULATORS.md).

| Task | Depends | Modules | Tests | 50-symbol simulated-day benchmark | Status |
|---|---|---|---|---|---|
| T00 | — | Scaffold, docs, config, schema | 10 pytest tests pass | N/A: scaffold; simulator begins at T01 | DONE |
| T01 | T00 | Official V3 feed/history simulators, decode | 20 T01 cases; full suite 30 passing | 29,992 ticks/s; 50 stocks + 3 indices, 6h | DONE |
| T02 | T01 | auth/core.py, ops/preflight.py | 14 new tests; full suite 44 passing | N/A: auth/preflight, not a per-tick feature | DONE |
| T03 | T01 | ingest/recorder.py | 8 new tests; full suite 52 passing; 6h lossless | 73,660 tick-equivalents/s; 50 stocks+3 indices; 21,600 frames, zero drops | DONE |
| T04 | T01 | trades/core.py, bars/core.py, schema mid_price | 13 T04 cases; full suite 96 passing | 15,153 ticks/s; 50 stocks+3 indices, 6h; classification+1m bars | DONE |
| T05 | T01 | ingest/history.py | 6 new tests; full suite 58 passing | N/A: daily REST/import I/O; no per-tick metric | DONE |
| T06 | T04 | layers/orderflow/footprint.py | 6 known-answer/truncation cases; full staged task suite green | 19,132 ticks/s; 50 stocks+3 indices, six-hour cached simulation | DONE |
| T07 | T04 | Depth/OFI/sweeps/iceberg | Not run; T04 pending | Not run for this task | NOT STARTED |
| T08 | T06 | Flow events/VPIN/Kyle | Not run; T06 pending | Not run for this task | NOT STARTED |
| T09 | T04 | Profiles/naked POC/IB | Not run; T04 pending | Not run for this task | NOT STARTED |
| T10 | T04 | VWAP/bands/anchors/events | Not run; T04 pending | Not run for this task | NOT STARTED |
| T11 | T04 | SMC structures/pools/sweeps | Not run; T04 pending | Not run for this task | NOT STARTED |
| T12 | T04 | Prior levels/opening ranges/gaps | Not run; T04 pending | Not run for this task | NOT STARTED |
| T13 | T03, T04 | Index/VIX/RS/breadth/context | Not run; T03/T04 pending | Not run for this task | NOT STARTED |
| T14 | T09–T12 | Zone engine | Not run; T09–T12 pending | Not run for this task | NOT STARTED |
| T15 | T08, T13, T14 | S1–S5/plans/cost gate/sizing | Not run; dependencies pending | Not run for this task | NOT STARTED |
| T16 | T15 | Unified live/replay engine | Not run; T15 pending | Not run for this task | NOT STARTED |
| T17 | T16 | Backtest/event study/shadow/edge board | Not run; T16 pending | Not run for this task | NOT STARTED |
| T18 | T02, T03, T05 | ops/runtime.py, ops/cli.py, systemd, install.sh, RUNBOOK | 9 ops tests; full suite 67 passing; unit verification and offline clean-container install dry-run | N/A: ops; T03 recorder benchmark 73,660 tick-equivalents/s | DONE |
| T19 | T16 | Read-only live view | Not run; T16 pending | Not run for this task | NOT STARTED |

Requested priority on resume: T01 → T02/T03/T05 → T18 → T04 → T06–T13 in
dependency order → T14 → T15 → T16 → T17/T19.

GitHub connector write access was verified on 2026-10-02 and the initialized
remote main was reconciled into this branch. Full publication is being retried
from the recovered workspace; the previous denial is retained as audit history.
