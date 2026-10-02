# T00 scaffold: preserve bootstrap v2 and record offline test blocker

The repository was empty. This change preserves the supplied v2 PDF and full
Markdown extraction, copies section 1 verbatim into AGENTS.md, and supplies the
T00 package scaffold, section documents, parameters, Arrow contracts and tests.
It does not provide a deployable recorder.

## Validation

All 10 pytest tests pass, including Arrow IPC schema serialization and the
Parquet tick round-trip. `pip check` reports no broken requirements. The owner
explicitly authorized network package installation on 2026-10-02; no live
Upstox call was made. SDK 2.30.0 provides official V3 generated classes, verified
by importing FeedResponse. No test was weakened, removed or changed.

## Task results

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

## Remaining work and blockers

- T00 dependency blocker is resolved; T01 is eligible.
- T01–T19 remain unimplemented; no simulated-day benchmark exists yet.
- Official V3 classes are now installed. Source notes still record the ambiguous
  FVG comparison and unspecified parameters for resolution in their tasks.
- GitHub publishing remains blocked by HTTP 403 (see PUBLISH.md).

Continue the requested recorder-first dependency order before deployment.

## Owner steps from RUNBOOK.md

**Deployment is blocked.** There is no recorder installer, OAuth CLI or systemd
unit yet; exact installation/start commands cannot be supplied truthfully.

After T18, the source specifies this sequence:

1. Clone, run the install script.
2. Put API key/secret/redirect URL and the Discord webhook in the files RUNBOOK.md
   names (600 perms).
3. Do the first OAuth login once.
4. Stop the old recorder first (one feed client per account), then start the new recorder.
5. Import existing recordings (T05 importer) so no recorded days are lost.
6. Run replay on recorded days; enable live research outputs after replay checks pass.

T18 must replace this blocked runbook with tested exact commands and file paths.

| Module | Tests | Status | Open issues |
|---|---|---|---|
| T00 docs/config/package scaffold | 10 pytest tests pass | DONE | None for T00 |
| T00 Arrow contracts | IPC and Parquet round-trip tests pass | Validated | Producers/consumers await later tasks |
| T01–T19 | Not executed | T01 ready; others pending | Implementation and simulator checks |

## Publication blocker

Git push and connector source-file publication both returned HTTP 403. No remote
branch or PR was created. Local commits and a Git bundle preserve the work; see
docs/stuck/PUBLISH.md for evidence and owner publication commands.
