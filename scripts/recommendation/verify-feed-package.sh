#!/usr/bin/env bash
set -Eeuo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd -P)
cd "$root"
python -m unittest tests.test_feed_service -v
python -m compileall -q feed feed_service
test -f api/feed-ranking-v1.yaml
git diff --check
echo "feed package verified: feed-rules-v1"
