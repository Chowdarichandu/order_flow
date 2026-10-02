#!/usr/bin/env bash
# Cloud is offline. Provision a complete wheelhouse before the task starts.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
if [[ -z "${ORDERFLOW_WHEELHOUSE:-}" || ! -d "$ORDERFLOW_WHEELHOUSE" ]]; then
  printf '%s\n' 'Set ORDERFLOW_WHEELHOUSE to a pre-provisioned local wheel directory.' >&2
  exit 1
fi
python -m pip install --no-index --find-links "$ORDERFLOW_WHEELHOUSE" -e '.[dev]'
# Official V3 protobuf sources/generated SDK classes must also be pre-provisioned.
# Never download or silently substitute a different wire format in a Cloud task.
