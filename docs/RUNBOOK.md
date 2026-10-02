# Owner runbook — recorder deployment blocked

**This repository is a T00 scaffold, not a deployable recorder.** T02 (auth),
T03 (recorder), T05 (history/import) and T18 (ops) are dependency-blocked by
unfinished T01 simulator/decoder task. No install script, OAuth CLI, systemd
units or recorder start command exists yet. Do not attempt to start live
recording from this branch.

## Resume build verification

Provision a local wheelhouse with every requirement in pyproject.toml and
provide official V3 protobuf classes. In the repository, run:

```bash
ORDERFLOW_WHEELHOUSE=/absolute/path/to/wheels bash scripts/codex_setup.sh
python -m pytest
```

These commands validate the scaffold. They do not install or start a recorder.
T00 now passes all 10 tests. Execute the dependency roadmap, prioritizing
T01 → T02/T03/T05 → T18. T18 must supply the exact credential file paths,
permissions, initial OAuth command, import command, replay verification,
installation command, services, holiday calendar and start/stop commands.

## Owner sequence from BOOTSTRAP.md section 7 (after T18)

1. Clone, run the install script.
2. Put API key/secret/redirect URL and the Discord webhook in the files RUNBOOK.md
   names (600 perms).
3. Do the first OAuth login once.
4. Stop the old recorder first (one feed client per account), then start the new recorder.
5. Import existing recordings (T05 importer) so no recorded days are lost.
6. Run replay on recorded days; enable live research outputs after replay checks pass.

Exact installation and recorder-start steps cannot be provided until those
modules exist and their simulator and clean-container checks pass. Supplying
invented commands or service names here would misrepresent deployment readiness.
