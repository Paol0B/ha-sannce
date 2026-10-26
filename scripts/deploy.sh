#!/usr/bin/env bash
# shellcheck disable=SC2029
set -euo pipefail

usage() {
  echo "usage: ${0##*/} HOST [CONTAINER=homeassistant] [CONFIG_PATH=/config]" >&2
  echo "CONFIG_PATH is the Home Assistant config directory on HOST." >&2
  echo "ENGINE=docker (default) or ENGINE=podman picks the container engine." >&2
  exit 2
}

[[ $# -ge 1 && $# -le 3 && $1 != -* ]] || usage

host=$1
container=${2:-homeassistant}
config=${3:-/config}
engine=${ENGINE:-docker}
case $engine in
  docker|podman) ;;
  *) echo "error: ENGINE must be docker or podman, got $engine" >&2; exit 2 ;;
esac

here="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
repo="$(dirname "$here")"
target="$config/custom_components/sannce"

ssh "$host" "mkdir -p -- $(printf '%q' "$target")"
rsync -a -s --delete --no-owner --no-group --exclude '__pycache__/' \
  "$repo/custom_components/sannce/" "$host:$target/"
ssh "$host" "$engine" restart "$container"
