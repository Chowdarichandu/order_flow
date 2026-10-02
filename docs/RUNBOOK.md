# Owner runbook — read-only recorder

RECORDER DEPLOYABLE: T02/T03/T05/T18 pass their simulator and install checks.
This means the recorder and owner ops are installable, not that live credentials
or a live feed have been exercised. Nothing places orders. Research/live
feature outputs remain disabled until their later tasks and replay checks pass.

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
backlog, not inferred exchange/trade latency. Degraded metrics deserve an alert.

## 6. Stop, repair and resume

```bash
systemctl --user stop orderflow-recorder.service
```

SIGTERM closes the socket and drains the queue. Published parts are fsynced and
atomically renamed. A power loss/SIGKILL can lose unflushed in-memory frames;
this is a data gap, not something to fill. Remove orphan `.tmp` files only after
confirming the recorder is stopped. Writer errors surface rather than hang.
Fix disk/capacity problems, inspect quality, renew OAuth if required, and restart
only one feed owner. Token 401/403 triggers one file reread; failures log status
and a sanitized response body. Never post credential files or webhook URLs in
issue reports.

## Cloud verification evidence

The full offline test suite covers auth, queue/writer failures, six-hour lossless
recording, reconnects, history/import idempotence, holidays, alerts/status and
installation. The installer dry-run also passed in a newly constructed minimal
Docker container with `--network none --read-only` and an empty owner home;
no image pull or setup network call was needed. Systemd timer syntax and rendered
unit files were verified with systemd-analyze. This is simulator verification;
no real account or live Upstox feed was accessed in Cloud.
