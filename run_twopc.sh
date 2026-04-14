#!/bin/bash
set -e

echo "Starting 2PC demo..."
docker compose down -v --remove-orphans
docker compose --profile twopc build
docker compose --profile twopc up --no-build -d twopc-coordinator twopc-p1 twopc-p2 twopc-p3 twopc-p4
sleep 3
docker compose --profile twopc run --rm --no-deps twopc-client python twopc_client.py "$@"

echo
echo "2PC node RPC logs:"
docker compose logs --tail=200 twopc-coordinator twopc-p1 twopc-p2 twopc-p3 twopc-p4
