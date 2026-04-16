# Jetson ZED 2i Stereo Capture System

Web-controlled stereo video capture system for NVIDIA Jetson with ZED 2i camera.

## Architecture

```
┌──────────────────────────────────────────────┐
│                  Jetson Nano                  │
│  +----------------------------------------+  │
│  │ Docker Host & NVIDIA Container Runtime │  │
│  +-----------------------+----------------+  │
│                          │                   │
│      Container A         │      Container B  │
│  (Video Capture)         │    (Web Server)   │
│                          │                   │
│   ZED SDK + GStreamer    │  FastAPI + UI     │
│   Stereo Recording       │  Control Panel    │
│                          │                   │
└──────────────────┬───────┴───────────────────┘
                   │
            Shared Volume
            /mnt/videos
```

## Features

- **Start/Stop Recording**: Control video capture via web UI
- **Real-time Status**: WebSocket-based live status updates
- **Video Management**: List, download, and delete recordings
- **Stereo Capture**: Full resolution side-by-side stereo from ZED 2i

## Requirements

- NVIDIA Jetson Nano (JetPack 4.6+)
- ZED 2i Camera connected via USB 3.0
- Docker with NVIDIA Container Runtime
- Network access to Jetson

## Quick Start

### 1. Clone/Copy to Jetson

```bash
# From your development machine
rsync -avz /path/to/jetson-zed/ jetson:/home/nvidia/jetson-zed/
```

### 2. Build and Run

```bash
ssh jetson
cd ~/jetson-zed

# Build containers
docker-compose build

# Start services
docker-compose up -d
```

### 3. Access Web UI

Open browser to: `http://<jetson-ip>:8080`

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Web UI |
| `/api/start` | POST | Start recording |
| `/api/stop` | POST | Stop recording |
| `/api/status` | GET | Current capture status |
| `/api/videos` | GET | List all recordings |
| `/api/video/{name}` | GET | Download video |
| `/api/video/{name}` | DELETE | Delete video |
| `/ws` | WebSocket | Real-time status updates |

## Configuration

### Environment Variables

- `VIDEO_DIR`: Video storage directory (default: `/mnt/videos`)
- `DISPLAY`: X11 display for ZED SDK (default: `:0`)

### Docker Compose Services

- **capture**: ZED SDK capture service
- **web**: FastAPI web server on port 8080

## Development

### Local Testing (Mac)

```bash
# Sync changes to Jetson
rsync -avz --exclude 'sync-jetson.sh' ~/jetson-zed/ jetson:/home/nvidia/jetson-zed/

# Rebuild on Jetson
ssh jetson "cd ~/jetson-zed && docker-compose build --no-cache"

# Restart services
ssh jetson "cd ~/jetson-zed && docker-compose down && docker-compose up -d"

# View logs
ssh jetson "cd ~/jetson-zed && docker-compose logs -f"
```

### File Structure

```
jetson-zed/
├── docker-compose.yml
├── README.md
├── capture/
│   ├── Dockerfile
│   ├── capture_service.py
│   ├── start_capture.sh
│   └── stop_capture.sh
├── web/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── app/
│   │   └── main.py
│   ├── templates/
│   │   └── index.html
│   └── static/
│       ├── style.css
│       └── app.js
└── videos/
    └── (recorded files)
```

## Troubleshooting

### Camera not detected

```bash
# Check USB devices
lsusb | grep -i stereo

# Check video devices
ls -la /dev/video*

# Restart capture container
docker-compose restart capture
```

### Web UI not accessible

```bash
# Check container status
docker-compose ps

# Check web container logs
docker-compose logs web

# Verify port binding
netstat -tlnp | grep 8080
```

### Recording issues

```bash
# Check capture container logs
docker-compose logs capture

# Verify shared volume
docker-compose exec web ls -la /mnt/videos
```

## License

MIT License
