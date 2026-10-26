#!/usr/bin/env bash
set -euo pipefail

here="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
repo="$(dirname "$here")"
python="$repo/.venv/bin/python"
hassfest_image="ghcr.io/home-assistant/hassfest@sha256:4b1adfb1e0a37710af0390708eb8000230b80b2193ccffbeed0a901fa9765181"
min_coverage=95

if [[ ! -x "$python" ]]; then
  echo "error: $python is missing; set up .venv as README.md, Development, says" >&2
  exit 1
fi
cd "$repo"

echo "== mypy"
"$python" -m mypy
echo "== mypy, library on Python 3.11"
"$python" -m mypy --python-version 3.11 lib/src/sannce_aio

echo "== unit tests and coverage"
"$python" -m pytest tests/components/sannce -q \
  --cov=custom_components/sannce --cov-report=term-missing:skip-covered
report=$(mktemp)
trap 'rm -f "$report"' EXIT
"$python" -m coverage json -q -o "$report"
"$python" - "$report" "$min_coverage" <<'EOF'
import json
import sys

minimum = float(sys.argv[2])
with open(sys.argv[1]) as file:
    files = json.load(file)["files"]
low = {
    name: data["summary"]["percent_covered"]
    for name, data in files.items()
    if data["summary"]["percent_covered"] < minimum
}
for name, percent in sorted(low.items()):
    print(f"error: {name} has {percent:.1f} % coverage, needs {minimum:g} %")
sys.exit(1 if low else 0)
EOF

echo "== quality scale"
# hassfest checks quality_scale.yaml for core integrations only, so check a copy
# installed as one that declares Platinum
output=$(docker run --rm -i -v "$repo/custom_components/sannce:/src/sannce:ro" \
  --entrypoint sh "$hassfest_image" -s <<'EOF'
set -e
cd /usr/src/homeassistant
cp -r /src/sannce homeassistant/components/sannce
python3 -c '
import json
path = "homeassistant/components/sannce/manifest.json"
with open(path) as file:
    manifest = json.load(file)
manifest["quality_scale"] = "platinum"
with open(path, "w") as file:
    json.dump(manifest, file)
'
echo "homeassistant.components.sannce.*" >> .strict-typing
python3 -m script.hassfest --action validate --plugins quality_scale \
  --integration-path homeassistant/components/sannce || true
EOF
)
echo "$output"
if ! grep -qx "Integrations: 1" <<<"$output"; then
  echo "error: hassfest did not check the integration" >&2
  exit 1
fi
reported=$(sed -n '/^Integration sannce/,/^$/p' <<<"$output" | sed '1d;/^$/d')
if [[ -n $reported ]]; then
  echo "error: hassfest reported quality scale errors" >&2
  exit 1
fi
echo "quality scale: yaml consistent, no hassfest errors"
