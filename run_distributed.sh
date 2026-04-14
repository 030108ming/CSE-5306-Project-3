#!/bin/bash

echo "Starting Distributed Architecture..."

docker compose down -v --remove-orphans
docker compose --profile distributed build
docker compose --profile distributed up -d
docker compose run --rm client