#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
: "${SITE_NAME:?SITE_NAME required}"
action="${1:-${ACTION:-auto}}"
if [[ "$action" == auto ]]; then
  if [[ "${RESTORE:-0}" == 1 ]]; then action=restore
  elif [[ -d "sites/$SITE_NAME" ]]; then action=update
  else action=create
  fi
fi
exec bash "$SCRIPT_DIR/site.sh" "$action"
