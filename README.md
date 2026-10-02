# orderflow-zero

Read-only NSE cash-equity market data and research on Upstox. Nothing in this
repository places orders.

The supplied [BOOTSTRAP.md](BOOTSTRAP.md) v2 is the source of truth. The original
[PDF](docs/BOOTSTRAP.pdf) is retained. See [roadmap](docs/ROADMAP.md),
[definitions](docs/DEFINITIONS.md), [architecture](docs/ARCHITECTURE.md),
[data contracts](docs/DATA_CONTRACTS.md), and [source notes](docs/SOURCE_NOTES.md).

Current status: T00 and T01 DONE, with all 30 tests passing. Official V3
feed/history simulators and decoders are implemented; the simulated six-hour
50-stock benchmark achieved 29,992 ticks/second for generation plus decoding.
See [T01 details](docs/SIMULATORS.md). T02/T03/T04/T05 are ready; T02–T19 remain
unimplemented. The recorder is not deployable yet. GitHub write access was
verified and publication is resuming.

## Offline development setup

Provision Python 3.11+ and a complete local wheelhouse, including build
requirements and all dependencies in `pyproject.toml`, before starting Cloud
work. Then run:

```bash
ORDERFLOW_WHEELHOUSE=/path/to/wheels bash scripts/codex_setup.sh
python -m pytest
```

The setup script only installs from local files. Tests need no token and must
never contact a live feed. The official V3 protobuf or generated SDK classes
must also be supplied before T01.

Limited scaffold checks can run with Python and PyYAML:

```bash
python -m unittest discover -s tests -p test_scaffold.py -v
```

These checks do not replace the full pytest gate or validate Arrow runtime
behavior. Configuration values marked `null` require a documented choice in
the relevant task; no unprovided metric parameter has an invented default.

Recorder owner steps are deferred to [RUNBOOK.md](docs/RUNBOOK.md), pending T18.

## EXPLORATORY Edge Scout

The public-candle research study is independent of the unfinished local
zone/setup roadmap. See [EDGE_SCOUT_REPORT.md](docs/EDGE_SCOUT_REPORT.md) for
out-of-sample family results and the exact local verification shortlist.
It uses no tokens, websocket or broker order endpoint. The user explicitly
requested unauthenticated public downloads for this study; tests stay offline.

```bash
python -m pip install -e '.[dev,research]'
python -m orderflow.research.edge_data --through 2026-10-01
python -m orderflow.research.edge_scout
python -m orderflow.research.edge_report
pytest -q
```

Raw data and resumable response/fold caches live under gitignored `data/`.
Current constituents, uncertified corporate-action adjustments and current
sector-index backcasts limit what these exploratory statistics establish.
