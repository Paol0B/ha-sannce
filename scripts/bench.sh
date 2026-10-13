#!/usr/bin/env bash
set -euo pipefail

here="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
repo="$(dirname "$here")"
bench="$repo/bench"
python="$repo/.venv/bin/python"
client="$bench/hass_client.py"
compose=(docker compose -f "$bench/compose.yaml")
hassfest_image="ghcr.io/home-assistant/hassfest@sha256:4b1adfb1e0a37710af0390708eb8000230b80b2193ccffbeed0a901fa9765181"

usage() {
  cat >&2 <<'USAGE'
usage: bench.sh COMMAND
  up                   build and start the bench, onboard Home Assistant, add the camera
  down                 stop the bench, keep the Home Assistant state
  reset                stop, wipe bench/ha-config, start fresh
  test                 reset, then run the end-to-end suite and hassfest
  event KIND [on|off]  push a camera event: motion vehicle intrusion line tamper video_loss
  audio FILE           save the last talk session as WAV
  hassfest             validate custom_components/sannce
USAGE
  exit 2
}

need_python() {
  if [[ ! -x "$python" ]]; then
    echo "error: $python is missing; set up .venv as README.md, Development, says" >&2
    exit 1
  fi
}

start() {
  "$here/vendor-lib.sh"
  mkdir -p "$bench/media"
  [[ -d "$bench/ha-config" ]] || cp -r "$bench/ha-template" "$bench/ha-config"
  local running
  running=$("${compose[@]}" ps --status running --services)
  "${compose[@]}" up -d --build
  # Home Assistant reads custom_components only when it starts
  if grep -qx homeassistant <<<"$running"; then
    "${compose[@]}" restart homeassistant
  fi
  "$python" "$client" setup
}

wipe() {
  "${compose[@]}" down
  [[ -d "$bench/ha-config" ]] || return 0
  # Home Assistant runs as root, so only a container can delete its files
  docker run --rm -v "$bench/ha-config:/config" python:3.14.4-slim \
    find /config -mindepth 1 -delete
  rmdir "$bench/ha-config"
}

run_hassfest() {
  docker run --rm -v "$repo/custom_components:/github/workspace/custom_components:ro" \
    "$hassfest_image"
}

run_suite() {
  wipe
  start
  local status=0
  (cd "$repo" && "$python" -m pytest tests/e2e -q -p no:homeassistant --bench) || status=$?
  run_hassfest || status=$?
  return "$status"
}

[[ $# -ge 1 ]] || usage
command=$1
shift
case $command in
  up) [[ $# -eq 0 ]] || usage; need_python; start ;;
  down) [[ $# -eq 0 ]] || usage; "${compose[@]}" down ;;
  reset) [[ $# -eq 0 ]] || usage; need_python; wipe; start ;;
  test) [[ $# -eq 0 ]] || usage; need_python; run_suite ;;
  event) [[ $# -ge 1 && $# -le 2 ]] || usage; need_python; "$python" "$client" event "$@" ;;
  audio) [[ $# -eq 1 ]] || usage; need_python; "$python" "$client" audio "$1" ;;
  hassfest) [[ $# -eq 0 ]] || usage; run_hassfest ;;
  *) usage ;;
esac
