#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
owner_home="${HOME}"
dry_run=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) dry_run=true; shift ;;
    --home) owner_home="$2"; shift 2 ;;
    *) printf '%s\n' 'Usage: install.sh [--dry-run] [--home PATH]' >&2; exit 2 ;;
  esac
done
if "$dry_run"; then
  printf '%s\n' 'Would install .venv, owner config, and systemd user units.'
  printf '%s\n' 'Refresh 03:45 Asia/Kolkata; rescue 08:00; preflight 08:30; recorder 09:00–15:35; history 20:30.'
  for unit in "$repo_root"/ops/systemd/*; do basename "$unit"; done
  exit 0
fi
python3 -m venv "$repo_root/.venv"
"$repo_root/.venv/bin/python" -m pip install -e "$repo_root"
mkdir -p "$owner_home/.config/orderflow" "$owner_home/.config/systemd/user" "$owner_home/.local/share/orderflow"
chmod 700 "$owner_home/.config/orderflow"
"$repo_root/.venv/bin/python" - "$repo_root" "$owner_home" <<'PY'
from pathlib import Path
import sys
repo,owner=map(Path,sys.argv[1:])
config=owner/'.config/orderflow/config.yaml'
if not config.exists():
    config.write_text((repo/'config/owner.yaml').read_text().replace('@HOME@',str(owner)))
    config.chmod(0o600)
for source in (repo/'ops/systemd').iterdir():
    target=owner/'.config/systemd/user'/source.name
    target.write_text(source.read_text().replace('@ROOT@',str(repo)))
PY
systemctl --user daemon-reload
printf '%s\n' 'Installed. Configure credentials, calendar, instruments and webhook before enabling timers. See docs/RUNBOOK.md.'
