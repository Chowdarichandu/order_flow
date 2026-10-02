# Recorder deployable milestone and roadmap results

**RECORDER DEPLOYABLE.** Auth, preflight, recorder, history/import and owner ops
are installable with systemd user services. Nothing places orders. T00/T01 were
already merged; this change adds the recorder milestone and tested independent
research layers. Fourteen tasks are DONE and six are STUCK. This does not claim
an end-to-end setup/research engine is complete.

The final offline suite passes **217 tests plus 92 subtests**. It includes
known-answer metrics, truncation/availability, official V3 protobuf edge cases,
secure token rereads/redaction, websocket failures, writer/reconnect failures,
history/import idempotence, holidays and status/alerts. No test was weakened or
deleted. No live Upstox call, account or secret was used. The final staged source
tree was tested; package construction uses the offline build environment.

The installer dry-run passed in a newly constructed clean Docker container
with network disabled and a read-only root filesystem. Rendered systemd units
and timers passed systemd-analyze verification. Tests cover receive-loop queue
isolation. The six-hour recorder simulation wrote all 21,600 multiplexed frames
with zero drops/unwritten frames; it is accelerated simulation, not six hours
of measured production latency. Crash-safe published parts cannot preserve
frames still in memory during power loss.

## STUCK reasons and resume requirements

- **T11:** PDF page 6 describes a minimum FVG gap but visibly prints
  `= 0.1 x ATR`. Text and image inspection did not resolve equality versus
  `>=`. Both explicit comparator variants have tests; the project default
  remains null. ATR smoothing and swing-tie policies also require explicit
  choices. See `docs/stuck/T11.md`.
- **T14:** The zone core and adapters have 13 tests but the task requires T11
  DONE. Supply explicit linkage/freshness/side/touch/invalidation policies and
  validate minute-by-minute composition from all canonical layers after T11.
- **T15:** Requires T14; S5 direction confirmation and risk per trade also need
  explicit policies. No setup implementation or benchmark was attempted.
- **T16:** Requires T15. Decoder replay exists; unified research live/replay
  equivalence is not claimed.
- **T17:** Requires T16; walk-forward train/test/purge/embargo choices are unset.
  No profitability validation, backtester or shadow ledger is claimed.
- **T19:** Requires T16. No live-view implementation is claimed.

Dependency-blocked tasks are not reported as failed tests. Details and exact
resume criteria are in `docs/stuck/T##.md` and `docs/status/T##.md`. None blocks
the read-only recorder installation. Daily OAuth is a fresh owner-approved code
exchange; the jobs cannot create an authorization token without owner login.

## Benchmark scope

Every metric benchmark uses the deterministic six-hour fixture with 50 stocks
plus three context instruments (1,144,800 source ticks). Cached-stage results
exclude simulator/decoder cost unless stated. **tick-eq/s** divides that source
tick count by a bar-stage runtime; it does not mean the stage consumes raw ticks.
T11's explicit equality fixture produced no structure events and does not prove
strategy quality. T13 measures a final snapshot with unavailable year-long VIX
and 20-session liquidity inputs null/flagged. T14 uses crafted active components
and compact upstream bar provenance, excludes upstream layers/raw leaf expansion,
and is not a full pipeline timing. Its first full-provenance benchmark session
was interrupted without a timing result; the documented compact fixture is the
second attempt. T09 measures the final profile, T10 only VWAP features, and T08
excludes pre-session daily bucket derivation. Raw evidence lives in
`docs/benchmarks/T##.json`; no profitability inference follows from throughput.

## Exact owner steps from RUNBOOK.md

The following install, private-input, daily OAuth, import/replay and recorder
start sections are copied verbatim from `docs/RUNBOOK.md`. Complete them before
enabling the timers. Stop the old feed owner before starting this recorder.

## 1. Install on Linux

Use Python 3.11+ and systemd user services. From an owner shell:

```bash
git clone https://github.com/Chowdarichandu/order_flow.git
cd order_flow
# Check out the recorder milestone branch until its changes are merged.
git checkout codex/recorder-milestone
bash scripts/install.sh --dry-run
bash scripts/install.sh
```

The installer creates `.venv`, installs the package, creates
`~/.config/orderflow/config.yaml`, copies units to `~/.config/systemd/user`, and
reloads systemd. It deliberately leaves timers disabled until you finish setup.
Keep the clone at its installation path; units reference that absolute path.
For unattended user services, ask your administrator to enable linger for your
Linux user (`loginctl enable-linger "$USER"`). Never run a second feed owner.

## 2. Private files and inputs

Create API credentials without putting secrets in command arguments, shell
history or environment variables:

```bash
.venv/bin/python - <<'PY'
from pathlib import Path
import getpass, json, os
folder=Path.home()/'.config/orderflow'
path=folder/'credentials.json'
values={'client_id':getpass.getpass('Upstox API key: '),
        'client_secret':getpass.getpass('Upstox API secret: '),
        'redirect_uri':input('Registered redirect URL: ').strip()}
fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
os.fchmod(fd,0o600)
with os.fdopen(fd,'w') as handle: json.dump(values,handle)
path=folder/'webhook.json'
fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
os.fchmod(fd,0o600)
with os.fdopen(fd,'w') as handle:
    json.dump({'url':getpass.getpass('Discord webhook URL: ')},handle)
PY
```

Populate `~/.config/orderflow/nse-holidays.json` from the complete official NSE
cash-market holiday calendar for every year you will schedule:
`{"holidays":["YYYY-MM-DD", ...]}`. Weekends are skipped automatically. Keep it
updated annually. A missing/invalid calendar emits a SOFT alert and cannot be
used to block recording; the program cannot infer unprovided exchange holidays.

Populate `~/.config/orderflow/instruments.json` from Upstox's instrument master
as a nonempty JSON object mapping instrument keys to symbols. Include your
cash equities plus `NSE_INDEX|Nifty 50`, `NSE_INDEX|Nifty Bank` and
`NSE_INDEX|India VIX`. Confirm actual keys against the owner's current master.
No guessed or placeholder equity keys should be enabled. Choose 5-level `full`
or plan-supported 30-level `full_d30` in config.yaml. Choose only one feed client.

## 3. OAuth login and daily renewal

Upstox daily tokens expire around 03:30 IST. This implementation exchanges a
fresh owner-approved authorization code; it does not invent a refresh-token
grant or automate login/2FA. **Repeat the following daily before recording**, not
just once. The 03:45 refresh job and 08:00 rescue job exchange a fresh code file
if present, or alert that login is needed. They cannot mint a token without
owner authorization.

```bash
.venv/bin/python -m orderflow.ops.cli oauth-url
```

Open the printed URL, complete Upstox login, and copy the full redirected URL.
Within ten minutes, store its code and actual returned state securely:

```bash
.venv/bin/python - <<'PY'
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import getpass, json, os
query=parse_qs(urlparse(getpass.getpass('Full OAuth callback URL: ')).query)
path=Path.home()/'.config/orderflow/code.json'
fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
os.fchmod(fd,0o600)
with os.fdopen(fd,'w') as handle:
    json.dump({'code':query['code'][0],'state':query['state'][0]},handle)
PY
.venv/bin/python -m orderflow.ops.cli refresh
.venv/bin/python -m orderflow.ops.cli preflight
```

`token.json` is atomically written at 0600 and the one-use code/state files are
removed. Do not print the token or pass it via an environment variable. Missing
or expired token and persistent non-200 feed authorization are HARD gates.
Other preflight failures are SOFT alerts. Scheduled preflight retries from
08:30 until 09:10 IST; the recorder rechecks its own hard gates before connecting.

## 4. Import and replay existing recordings

```bash
.venv/bin/python -m orderflow.ops.cli import --source /absolute/path/to/old-recordings
.venv/bin/python -m orderflow.ops.cli replay
```

The importer supports this repo's canonical raw-message, TickEvent and candle
Parquet contracts, preserves source files and raw bytes, and tracks file hashes
for idempotence. Unknown legacy schemas are explicitly refused. Provide an
adapter or a sample for conversion rather than relabelling columns or inventing
timestamps. Do not place the import destination inside the source tree.

Replay decodes persisted raw packets through the same V3 decoder into
`~/.local/share/orderflow/replay`. Check quality flags, sessions, prices, depth
and timestamps. This is decoder replay; the unified research engine arrives in
T16. Do not enable live research outputs before its equivalence checks pass.

Optional backfill, resumable from the manifest:

```bash
.venv/bin/python -m orderflow.ops.cli history --start 2022-01-01 --end YYYY-MM-DD
```

Only complete official calendar input permits distinguishing exchange holidays
from missing historical responses. Downloader writes explicit GAP/ERROR records,
never interpolates. Official bhavcopy CSV must be parsed into daily OHLCV inputs
for `ingest.history.cross_check`; it reports differences, including delivery %
when supplied. Automated bhavcopy retrieval and unknown legacy adapters are not
included.

## 5. Start the recorder first

Stop the old recorder using its existing service/command **before starting this
one**. The new recorder's flock protects only cooperating clients using its lock;
it cannot terminate an external legacy client or enforce Upstox account limits.

After credentials, calendar, instrument list and replay checks:

```bash
systemctl --user enable --now orderflow-refresh.timer orderflow-rescue.timer \
  orderflow-preflight.timer orderflow-recorder.timer orderflow-stop.timer \
  orderflow-history.timer
systemctl --user list-timers 'orderflow-*'
# Optional immediate start during the recording window, after stopping the old client:
systemctl --user start orderflow-recorder.service
```

Times are explicitly Asia/Kolkata: refresh 03:45, rescue 08:00, preflight 08:30,
recorder 09:00, stop 15:35, nightly history 20:30. Every scheduled data job checks
weekends and the configured NSE calendar; holidays write HOLIDAY status, never
failed-day records. The stop timer is harmless even with no running service.

Inspect without revealing private files:

```bash
systemctl --user status orderflow-recorder.service
journalctl --user -u orderflow-recorder.service --since today
cat ~/.local/share/orderflow/status.json
cat ~/.local/share/orderflow/quality/YYYY-MM-DD.json
```

Raw multiplexed protobuf packets are stored intact as canonical RawMessage
Parquet under `~/.local/share/orderflow/raw/YYYY-MM-DD/part-*.parquet`, using IST
receipt dates. No disk operation occurs in the websocket receive loop. Queue
capacity, batching, flush and reconnect/heartbeat settings are in owner config.
The daily quality report counts gaps/resets/duplicates/out-of-order, drops,
disconnects, decode failures and unwritten packets. Max queue lag measures writer
backlog, not inferred exchange/trade latency. With decoding enabled, maximum
exchange lag measures receipt minus exchange time off the receive loop. Negative
lag is counted separately as clock skew; missing exchange timestamps are counted.
These are snapshot timing metrics. Degraded metrics deserve an alert.

Recorder coverage is 09:00–15:35 IST. Derived cash-session trades/bars and
profile/VWAP inputs use [09:15, 15:30) IST by default; outside messages remain
in the audit data. A historical candle ending at 15:30 is eligible. Final time
buckets extending beyond close remain unclosed and omitted: the 60-minute
15:15–16:15 bucket is never represented as a completed bar.


## Task/module/test results

Test counts overlap where shared guards/status coverage are referenced; the
full-suite count is 217. N/A benchmarks apply to non-metric tasks.

| Task | Modules | Tests | Simulated 50-symbol-day benchmark | Status | Open issues |
|---|---|---|---|---|---|
| T00 | Scaffold/docs/config/schema | 10 | N/A | DONE | Already merged baseline |
| T01 | V3 simulators/decoder | 20 | 29,992 ticks/s; generation + decode | DONE | Already merged; controlled fixtures |
| T02 | OAuth/token/preflight | 21 | N/A: auth | DONE | Daily owner OAuth approval required |
| T03 | Feed/queue/Parquet/quality | 15 | 73,537 tick-eq/s; generation + raw writer | DONE | Zero drops; live broker untested |
| T04 | Trades/time/volume/history bars | 22 + 3 shared session guards | 14,231 ticks/s; classification + 1m bars | DONE | Final incomplete 60m bucket omitted |
| T05 | History/downloader/import | 6 | N/A: history I/O | DONE | Unknown legacy schemas need adapter; bhavcopy input supplied locally |
| T06 | Footprint/delta/CVD/imbalances | 6 | 17,491 ticks/s; footprint only | DONE | Shared session guards also apply |
| T07 | Depth/OFI/sweeps/iceberg | 15 | 986 ticks/s; 19.46m feature rows | DONE | Explicit trailing/window policies required |
| T08 | Flow/VPIN/Kyle | 21 | 5,025 ticks/s; includes T06 | DONE | Daily VPIN parameter derivation excluded; explicit dominance/return convention |
| T09 | Profiles/composites/naked POC/IB | 6 | 32,249 ticks/s; final session profile only | DONE | Minute update/composite/IB timings excluded |
| T10 | VWAP/bands/anchors/events | 15 | 14,728 ticks/s; VWAP features only | DONE | Event timing excluded |
| T11 | SMC structures/lifecycle | 13 | 234,095 tick-eq/s; cached bars, explicit eq fixture | STUCK | FVG equality versus minimum unresolved; explicit ATR/tie policies |
| T12 | Prior levels/OR/gaps | 13 | 274,065 tick-eq/s; 4,568 bars/s | DONE | Optional round interval explicit |
| T13 | Index/VIX/RS/breadth/context | 10 | 282,428 tick-eq/s; final context snapshot | DONE | Missing long VIX/liquidity histories are null and flagged |
| T14 | Zone clustering/lifecycle/adapters | 13 | 7,785 tick-eq/s; compact-provenance fixture | STUCK | Requires T11 DONE and full canonical-layer composition |
| T15 | Setup/plans dependency report | Not run | Not run | STUCK | Requires T14; S5 confirmation/risk unset |
| T16 | Unified-engine dependency report | Not run | Not run | STUCK | Requires T15 |
| T17 | Research dependency report | Not run | Not run | STUCK | Requires T16; train/test/purge/embargo unset |
| T18 | Ops/systemd/install/RUNBOOK | 8 + status-writer coverage | N/A: ops; T03 benchmark applies | DONE | Owner calendar/instruments/private files required |
| T19 | Read-only-view dependency report | Not run | Not run | STUCK | Requires T16 |
