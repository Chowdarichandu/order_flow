# T00–T01: bootstrap and official V3 simulator foundation

Adds the supplied bootstrap v2 source, permanent rules, exact-definition documents,
all configured section 4 parameters, canonical Arrow schemas, and official V3
feed/history simulators with quality-aware decoders. No live Upstox connection or
order-placement code is used. The recorder is not deployable yet.

## Validation

All 30 tests pass (20 T01 cases plus 10 scaffold/schema tests). Coverage includes
5/30-level stock depth, Nifty/Bank Nifty/VIX, LTPC/first-level modes, gaps, resets,
duplicates, out-of-order frames, disconnect/403/expired-token fixtures, official
protobuf round-trip, Arrow/Parquet schemas, candle known answers and truncation.
No test was weakened or removed. Upstox SDK 2.30.0 supplies the official classes.

Six-hour 50-stock simulation plus three context instruments: 21,600 snapshots,
1,144,800 rows, 38.17 seconds, 29,992 ticks/second for generation + decoding.
This is not a recorder throughput benchmark; T03 will measure queue/writer I/O.
Raw result: docs/benchmarks/T01.json.

## Task results

| Task | Depends | Modules | Tests | 50-symbol simulated-day benchmark | Status |
|---|---|---|---|---|---|
| T00 | — | Scaffold, docs, config, schema | 10 pytest tests pass | N/A: scaffold; simulator begins at T01 | DONE |
| T01 | T00 | Official V3 feed/history simulators, decode | 20 T01 cases; full suite 30 passing | 29,992 ticks/s; 50 stocks + 3 indices, 6h | DONE |
| T02 | T01 | OAuth/token refresh, preflight | Not run; eligible next | Not run for this task | READY |
| T03 | T01 | Feed/queue/Parquet recorder, quality | Not run; eligible next | Not run for this task | READY |
| T04 | T01 | Trades, time/volume bars | Not run; eligible next | Not run for this task | READY |
| T05 | T01 | History downloader, bhavcopy, importer | Not run; eligible next | Not run for this task | READY |
| T06 | T04 | Footprint/delta/CVD/imbalances | Not run; T04 pending | Not run for this task | NOT STARTED |
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
| T18 | T02, T03, T05 | Ops/install/systemd/runbook | Not run; dependencies pending | Not run for this task | NOT STARTED |
| T19 | T16 | Read-only live view | Not run; T16 pending | Not run for this task | NOT STARTED |

## Remaining work

T02/T03/T04/T05 are eligible next. T02–T19 are not implemented and their criteria
are not claimed. Resume recorder-first: T02/T03/T05 → T18, then T04 and the layers
in dependency order, then zones/setups/engine/research/UI. Source notes record
unspecified parameters and the PDF's ambiguous FVG comparator. The original
missing-dependency blocker is resolved and retained as audit history.

## Owner steps from RUNBOOK.md

Deployment remains unavailable: there is no installer, OAuth CLI or systemd
recorder unit yet. Exact commands will be supplied and validated in T18. The
source's owner sequence after T18 is:

1. Clone, run the install script.
2. Put API key/secret/redirect URL and the Discord webhook in the files RUNBOOK.md
   names (600 perms).
3. Do the first OAuth login once.
4. Stop the old recorder first (one feed client per account), then start the new recorder.
5. Import existing recordings (T05 importer) so no recorded days are lost.
6. Run replay on recorded days; enable live research outputs after replay checks pass.

| Module | Tests | Status | Open issues |
|---|---|---|---|
| T00 docs/config/schema | 10 tests pass | DONE | Derived producers await later tasks |
| T01 simulator/decoders | 20 tests pass; full suite green; six-hour benchmark | DONE | Fixtures are controlled, not market-calibrated |
| T02–T19 | Not implemented | Pending | Full recorder/research roadmap remains |
