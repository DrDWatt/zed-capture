#!/bin/bash
# View logs from ZED Capture services
cd "$(dirname "$0")/.."

docker-compose logs -f "$@"
