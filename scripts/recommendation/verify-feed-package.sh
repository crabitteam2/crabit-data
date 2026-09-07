#!/usr/bin/env bash
set -Eeuo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd -P)
cd "$root"
if [[ ${CRABIT_BACKEND_OPENAPI+x} == x ]]; then
  test -f "$CRABIT_BACKEND_OPENAPI"
  python scripts/recommendation/sync-feed-contract.py "$CRABIT_BACKEND_OPENAPI" --check
fi
python -m unittest tests.test_feed_contract_projection tests.test_feed_service -v
python -m compileall -q feed feed_service
git diff --check
echo "feed package verified: feed-rules-v1"
