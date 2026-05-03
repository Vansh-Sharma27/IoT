#!/usr/bin/env bash
# vm_server/deploy/smoke_test.sh
#
# End-to-end smoke test against a running vision service. No hardware required.
#
# Usage:
#     bash vm_server/deploy/smoke_test.sh <URL> <TOKEN> <IMAGE_PATH>
#     # or via env:
#     URL=http://127.0.0.1:8000 TOKEN=xxx IMAGE=./alice.jpg bash vm_server/deploy/smoke_test.sh
#
# Exits non-zero on any failed check.

set -euo pipefail

URL="${1:-${URL:-}}"
TOKEN="${2:-${TOKEN:-}}"
IMAGE="${3:-${IMAGE:-}}"

if [[ -z "$URL" || -z "$TOKEN" || -z "$IMAGE" ]]; then
    echo "usage: smoke_test.sh <URL> <TOKEN> <IMAGE_PATH>" >&2
    exit 2
fi
if [[ ! -f "$IMAGE" ]]; then
    echo "image not found: $IMAGE" >&2
    exit 2
fi

echo "==> 1/3 GET $URL/ping"
curl -sf "$URL/ping"; echo

echo "==> 2/3 GET $URL/known"
curl -sf -H "Authorization: Bearer $TOKEN" "$URL/known"; echo

echo "==> 3/3 POST $URL/authenticate (image=$IMAGE)"
curl -sf -X POST \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/octet-stream" \
    --data-binary "@$IMAGE" \
    "$URL/authenticate"; echo

echo "==> all 3 checks passed"
