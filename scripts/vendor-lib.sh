#!/usr/bin/env bash
set -euo pipefail
here="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
repo="$(dirname "$here")"
mkdir -p "$repo/custom_components/sannce"
rsync -a --delete --exclude '__pycache__/' \
  "$repo/lib/src/sannce_aio/" "$repo/custom_components/sannce/sannce_aio/"
