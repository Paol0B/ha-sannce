#!/usr/bin/env bash
set -euo pipefail

here="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
repo="$(dirname "$here")"
remote=sannce-aio
url=https://github.com/Paol0B/sannce-aio.git

usage() {
  cat >&2 <<'USAGE'
usage: publish-lib.sh [--tag vX.Y.Z]
  (no option)   split lib/ and push it to master of the sannce-aio repository
  --tag vX.Y.Z  also tag the split head and push the tag, which starts the PyPI release
Run it from master. The branch publication may push without --tag.
USAGE
  exit 2
}

tag=
case $# in
  0) ;;
  2) [[ $1 == --tag && $2 =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || usage; tag=$2 ;;
  *) usage ;;
esac

cd "$repo"

if [[ -n $(git status --porcelain) ]]; then
  echo "error: the working tree is not clean" >&2
  exit 1
fi

branch=$(git branch --show-current)
if [[ $branch != master && ( $branch != publication || -n $tag ) ]]; then
  echo "error: HEAD is '${branch:-detached}'; publish from master (publication only without --tag)" >&2
  exit 1
fi

if [[ -n $tag ]]; then
  version=$(git show HEAD:lib/pyproject.toml | sed -n 's/^version = "\(.*\)"$/\1/p')
  if [[ v$version != "$tag" ]]; then
    echo "error: lib/pyproject.toml has version '$version', not '${tag#v}'" >&2
    exit 1
  fi
fi

if current=$(git remote get-url "$remote" 2>/dev/null); then
  if [[ $current != "$url" ]]; then
    echo "error: remote $remote is $current, expected $url" >&2
    exit 1
  fi
else
  git remote add "$remote" "$url"
fi

head=$(git subtree split --prefix=lib HEAD)
echo "branch $branch, split commit $head"
git push "$remote" "$head:refs/heads/master"
if [[ -n $tag ]]; then
  git push "$remote" "$head:refs/tags/$tag"
fi
