#!/bin/bash
# Build Docker containers for Jetson Orin NX
set -e

cd "$(dirname "$0")/.."

echo "Building ZED Capture containers for Orin NX..."
docker-compose -f docker-compose.orin.yml build --no-cache

echo ""
echo "Build complete. Start with: ./scripts/start-orin.sh"
