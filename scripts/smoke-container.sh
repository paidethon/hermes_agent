#!/usr/bin/env bash
# scripts/smoke-container.sh — build the production image and run the REAL
# container gate locally (Linux with Docker; CI runs tests/smoke_container.py
# directly after its own build). Cleans up containers and volumes on exit.
#
# Usage: scripts/smoke-container.sh [--image NAME]
set -euo pipefail
cd "$(dirname "$0")/.."

IMAGE="hermes-recovery:smoke-$(git rev-parse --short HEAD 2>/dev/null || echo local)"
if [ "${1:-}" = "--image" ] && [ -n "${2:-}" ]; then IMAGE="$2"; fi

echo "== building $IMAGE =="
docker buildx build --load --tag "$IMAGE" \
    --build-arg "SOURCE_COMMIT=$(git rev-parse HEAD 2>/dev/null || echo unknown)" .

echo "== real container gate =="
TEST_IMAGE="$IMAGE" python3 tests/smoke_container.py

echo "== smoke PASSED: $IMAGE =="
