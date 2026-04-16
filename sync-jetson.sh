#!/bin/bash
# Sync a local project folder to Jetson Nano
# Usage: sync-jetson.sh <local-project-path> [remote-path]

PROJECT="${1:-.}"
REMOTE_PATH="${2:-/home/nvidia/$(basename "$PROJECT")}"

if [ ! -d "$PROJECT" ]; then
    echo "Error: Directory '$PROJECT' does not exist"
    exit 1
fi

echo "Syncing '$PROJECT' to jetson:$REMOTE_PATH"
echo "Press Ctrl+C to stop watching"
echo "---"

# Initial sync
rsync -avz --exclude '.git' --exclude '__pycache__' --exclude '*.pyc' --exclude 'node_modules' \
    "$PROJECT/" "jetson:$REMOTE_PATH/"
echo "Initial sync complete at $(date)"
echo "Watching for changes..."

# Watch for changes and sync
fswatch -o "$PROJECT" | while read; do
    rsync -avz --exclude '.git' --exclude '__pycache__' --exclude '*.pyc' --exclude 'node_modules' \
        "$PROJECT/" "jetson:$REMOTE_PATH/"
    echo "Synced at $(date)"
done
