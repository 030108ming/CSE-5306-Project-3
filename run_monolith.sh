#!/bin/bash

echo "Starting Monolithic Architecture..."

docker compose down -v --remove-orphans
docker compose --profile monolith build
docker compose --profile monolith up -d
docker compose run --rm client