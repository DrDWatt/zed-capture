#!/bin/bash
# Start ZED Capture containers on Jetson Orin NX
set -e

cd "$(dirname "$0")/.."

echo "Starting ZED Capture containers..."
docker-compose -f docker-compose.orin.yml up -d

echo ""
echo "Containers started. Web UI: http://$(hostname -I | awk '{print $1}'):8080"
echo "Logs: docker-compose -f docker-compose.orin.yml logs -f"
