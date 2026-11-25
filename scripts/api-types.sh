#!/usr/bin/env bash
# Generate the web app's TypeScript types from the API's OpenAPI description.
#
#   scripts/api-types.sh          write web/src/api/types.ts
#   scripts/api-types.sh --check  fail if web/src/api/types.ts is out of date
#
# The description comes from the Python models (no server, no data needed), so a
# change in an API model that is not regenerated fails `make validate`.
set -euo pipefail
cd "$(dirname "$0")/.."

target=web/src/api/types.ts
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

uv run python -m map_routing.api.openapi > "$tmp/openapi.json"
(cd web && pnpm exec openapi-typescript "$tmp/openapi.json" -o "$tmp/types.ts" > /dev/null)

if [[ "${1:-}" == "--check" ]]; then
    if ! diff -q "$tmp/types.ts" "$target" > /dev/null; then
        echo "$target is out of date: run \`make api-types\`" >&2
        exit 1
    fi
else
    cp "$tmp/types.ts" "$target"
    echo "wrote $target"
fi
