#!/usr/bin/env bash
set -Eeuo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd -P)
cd "$root"
canonical_openapi=${CRABIT_BACKEND_OPENAPI:-"$(cd .. && pwd -P)/crabit-backend/api/openapi.yaml"}
test -f "$canonical_openapi"
python scripts/recommendation/sync-feed-contract.py "$canonical_openapi" --check
python -m unittest tests.test_feed_service -v
python -m compileall -q feed feed_service
git diff --check
echo "feed package verified: feed-rules-v1"
