#!/bin/bash
# Build Docker containers on Jetson
set -e

cd "$(dirname "$0")/.."

echo "Building ZED Capture containers..."
docker-compose build --no-cache

echo "Build complete!"
