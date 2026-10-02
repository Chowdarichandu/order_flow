# orderflow-zero

Read-only NSE cash-equity market data and research on Upstox. Nothing in this
repository places orders.

The supplied [BOOTSTRAP.md](BOOTSTRAP.md) v2 is the source of truth. The original
[PDF](docs/BOOTSTRAP.pdf) is retained. See [roadmap](docs/ROADMAP.md),
[definitions](docs/DEFINITIONS.md), [architecture](docs/ARCHITECTURE.md),
[data contracts](docs/DATA_CONTRACTS.md), and [source notes](docs/SOURCE_NOTES.md).

RECORDER DEPLOYABLE: T02/T03/T05/T18 provide secure file-based OAuth,
preflight, one feed owner, a bounded queue, atomic batched Parquet recording,
holiday-aware systemd jobs, alerts, status and installation. All verification is
offline against simulators; no live account has been tested. Daily OAuth requires
owner login. Follow [RUNBOOK.md](docs/RUNBOOK.md) to install and start the recorder.

Trades/bars, footprint, depth, flow, profile, VWAP, levels and context have causal
known-answer tests. SMC and zone APIs are implemented with explicit policies,
but T11/T14 remain STUCK on the source's FVG comparator; downstream setup,
unified-engine, validation and view tasks are dependency blocked. Research
outputs remain disabled. See [task status](docs/ROADMAP.md) and
[source blockers](docs/stuck/T11.md). Benchmarks state their measured stage and
separate ticks from bar-derived tick equivalents.

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
are supplied by the pinned official SDK dependency.

Limited scaffold checks can run with Python and PyYAML:

```bash
python -m unittest discover -s tests -p test_scaffold.py -v
```

These checks do not replace the full pytest gate or validate Arrow runtime
behavior. Configuration values marked `null` require a documented choice in
the relevant task; no unprovided metric parameter has an invented default.

Recorder owner steps are in [RUNBOOK.md](docs/RUNBOOK.md).
