#!/bin/bash
# Stop ZED Capture containers on Jetson Orin NX
set -e

cd "$(dirname "$0")/.."

echo "Stopping ZED Capture containers..."
docker-compose -f docker-compose.orin.yml down

echo "Containers stopped."
