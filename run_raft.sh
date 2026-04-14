#!/bin/bash
set -e

echo "Starting Raft demo..."
docker compose down -v --remove-orphans
docker compose --profile raft build
docker compose --profile raft up --no-build -d raft1 raft2 raft3 raft4 raft5
sleep 6
docker compose --profile raft run --rm --no-deps raft-client python raft_client.py status

echo
echo "Raft node RPC logs:"
docker compose logs --tail=120 raft1 raft2 raft3 raft4 raft5
