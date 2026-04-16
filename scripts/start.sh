#!/bin/bash
# Start ZED Capture services
set -e

cd "$(dirname "$0")/.."

echo "Starting ZED Capture services..."
docker-compose up -d

echo "Services started!"
echo "Web UI available at: http://$(hostname -I | awk '{print $1}'):8080"
