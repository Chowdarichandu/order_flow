# orderflow-zero

Read-only NSE cash-equity market data and research on Upstox. Nothing in this
repository places orders.

The supplied [BOOTSTRAP.md](BOOTSTRAP.md) v2 is the source of truth. The original
[PDF](docs/BOOTSTRAP.pdf) is retained. See [roadmap](docs/ROADMAP.md),
[definitions](docs/DEFINITIONS.md), [architecture](docs/ARCHITECTURE.md),
[data contracts](docs/DATA_CONTRACTS.md), and [source notes](docs/SOURCE_NOTES.md).

Current status: T00 DONE, with all 10 tests passing. The owner authorized
package installation and the official V3 protobuf is available from Upstox SDK
2.30.0. T01 is ready; T01–T19 are not implemented. This is not a deployable
recorder or a working research system. GitHub publishing remains blocked by
HTTP 403; see [publication evidence](docs/stuck/PUBLISH.md).

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
