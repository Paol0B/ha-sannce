#!/usr/bin/env bash
set -euo pipefail
here="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
repo="$(dirname "$here")"
if [[ ! -d "$repo/lib/src/sannce_aio" ]]; then
  echo "error: lib/src/sannce_aio is missing; run git submodule update --init" >&2
  exit 1
fi
mkdir -p "$repo/custom_components/sannce"
# Home Assistant gets the client only: the control API has no login
rsync -a --delete --delete-excluded --exclude '__pycache__/' \
  --exclude /simulator.py --exclude /simulator_rtsp.py --exclude /control.py \
  --exclude /__main__.py \
  "$repo/lib/src/sannce_aio/" "$repo/custom_components/sannce/sannce_aio/"
