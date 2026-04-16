#!/bin/bash
# Stop ZED Capture services
set -e

cd "$(dirname "$0")/.."

echo "Stopping ZED Capture services..."
docker-compose down

echo "Services stopped!"
