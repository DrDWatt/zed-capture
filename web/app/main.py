#!/usr/bin/env python3
"""
ZED Capture Web Server
FastAPI-based web UI for controlling ZED 2i stereo capture on Jetson.
"""

import os
import json
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional, List

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.websockets import WebSocket, WebSocketDisconnect

# WebRTC support (optional - requires aiortc)
try:
    from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration, RTCIceServer
    from stream import LiveCameraTrack
    WEBRTC_AVAILABLE = True
except ImportError:
    WEBRTC_AVAILABLE = False

# Configuration
VIDEO_DIR = os.environ.get("VIDEO_DIR", "/mnt/videos")
CONTROL_FILE = os.path.join(VIDEO_DIR, ".control")
STATUS_FILE = os.path.join(VIDEO_DIR, ".status")
SETTINGS_FILE = os.path.join(VIDEO_DIR, ".settings")
ANALYSIS_FILE = os.path.join(VIDEO_DIR, ".analysis")

# Default camera settings
DEFAULT_SETTINGS = {
    "resolution": "HD1080",
    "depthMode": "NEURAL",
    "autoExposure": False,
    "exposure": 75,
    "gain": 40,
    "autoWhiteBalance": False,
    "whiteBalance": 4500,
    "brightness": 5,
    "compression": "H265"
}

app = FastAPI(title="ZED Capture Control", version="1.0.0")

# Mount static files and templates
templates = Jinja2Templates(directory="/app/templates")
app.mount("/static", StaticFiles(directory="/app/static"), name="static")

# WebSocket connections for real-time updates
activeConnections: List[WebSocket] = []

# WebRTC peer connections
peerConnections: set = set()


def ensureDirectories():
    """Ensure required directories exist"""
    Path(VIDEO_DIR).mkdir(parents=True, exist_ok=True)


def sendCommand(command: str) -> bool:
    """Send command to capture service via control file"""
    try:
        with open(CONTROL_FILE, 'w') as f:
            f.write(command)
        return True
    except Exception as e:
        print(f"Error sending command: {e}")
        return False


def getStatus() -> dict:
    """Read current capture status"""
    try:
        if os.path.exists(STATUS_FILE):
            with open(STATUS_FILE, 'r') as f:
                content = f.read().strip()
            parts = content.split('|')
            if len(parts) >= 4:
                return {
                    "state": parts[0],
                    "message": parts[1],
                    "timestamp": parts[2],
                    "filename": parts[3]
                }
    except Exception as e:
        print(f"Error reading status: {e}")
    
    return {
        "state": "unknown",
        "message": "Unable to read status",
        "timestamp": datetime.now().isoformat(),
        "filename": ""
    }


def listVideos() -> List[dict]:
    """List all video files"""
    videos = []
    try:
        for f in sorted(Path(VIDEO_DIR).iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
            if f.is_file() and f.suffix.lower() in ['.mp4', '.mov', '.avi', '.svo', '.svo2']:
                if not f.name.startswith('.') and '_preview' not in f.name:
                    stat = f.stat()
                    isSvo = f.suffix.lower() in ['.svo', '.svo2']
                    # Check for companion preview MP4
                    previewFile = f.with_name(f.stem + '_preview.mp4')
                    hasPreview = previewFile.exists() if isSvo else True
                    previewName = previewFile.name if isSvo and hasPreview else f.name
                    videos.append({
                        "name": f.name,
                        "size": stat.st_size,
                        "sizeFormatted": formatSize(stat.st_size),
                        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                        "modifiedFormatted": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                        "isSvo": isSvo,
                        "hasPreview": hasPreview,
                        "previewName": previewName
                    })
    except Exception as e:
        print(f"Error listing videos: {e}")
    return videos


def formatSize(sizeBytes: int) -> str:
    """Format file size for display"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if sizeBytes < 1024:
            return f"{sizeBytes:.1f} {unit}"
        sizeBytes /= 1024
    return f"{sizeBytes:.1f} TB"


@app.on_event("startup")
async def startup():
    ensureDirectories()


@app.on_event("shutdown")
async def shutdown():
    """Clean up WebRTC connections on shutdown"""
    for pc in list(peerConnections):
        await pc.close()
    peerConnections.clear()


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Render main control page"""
    status = getStatus()
    videos = listVideos()
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"status": status, "videos": videos}
    )


@app.post("/api/start")
async def startRecording():
    """Start video recording"""
    status = getStatus()
    if status["state"] == "recording":
        return JSONResponse(
            status_code=400,
            content={"success": False, "message": "Already recording"}
        )
    
    if sendCommand("start"):
        await broadcastStatus()
        return {"success": True, "message": "Recording started"}
    return JSONResponse(
        status_code=500,
        content={"success": False, "message": "Failed to start recording"}
    )


@app.post("/api/stop")
async def stopRecording():
    """Stop video recording"""
    status = getStatus()
    if status["state"] != "recording":
        return JSONResponse(
            status_code=400,
            content={"success": False, "message": "Not recording"}
        )
    
    if sendCommand("stop"):
        await broadcastStatus()
        return {"success": True, "message": "Recording stopped"}
    return JSONResponse(
        status_code=500,
        content={"success": False, "message": "Failed to stop recording"}
    )


@app.get("/api/status")
async def apiStatus():
    """Get current capture status"""
    return getStatus()


@app.get("/api/settings")
async def getSettings():
    """Get current camera settings"""
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, 'r') as f:
                settings = json.load(f)
            # Merge with defaults for any missing keys
            merged = dict(DEFAULT_SETTINGS)
            merged.update(settings)
            return merged
    except Exception as e:
        print(f"Error reading settings: {e}")
    return dict(DEFAULT_SETTINGS)


@app.post("/api/settings")
async def updateSettings(request: Request):
    """Update camera settings"""
    try:
        newSettings = await request.json()
        # Merge with defaults
        settings = dict(DEFAULT_SETTINGS)
        settings.update(newSettings)
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings, f, indent=2)
        return {"success": True, "message": "Settings updated", "settings": settings}
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": str(e)}
        )


@app.post("/api/analyze")
async def analyzeScene():
    """Trigger pre-capture scene analysis"""
    status = getStatus()
    if status["state"] == "recording":
        return JSONResponse(
            status_code=400,
            content={"success": False, "message": "Cannot analyze while recording"}
        )
    
    # Clear previous analysis
    if os.path.exists(ANALYSIS_FILE):
        os.remove(ANALYSIS_FILE)
    
    if sendCommand("analyze"):
        # Poll for analysis result (capture service writes .analysis file)
        # Jetson Nano with NEURAL depth needs ~15-20s to grab+analyze frames
        for _ in range(60):  # Wait up to 30 seconds
            await asyncio.sleep(0.5)
            if os.path.exists(ANALYSIS_FILE):
                try:
                    with open(ANALYSIS_FILE, 'r') as f:
                        result = json.load(f)
                    return result
                except (json.JSONDecodeError, IOError):
                    continue
        return JSONResponse(
            status_code=504,
            content={"success": False, "message": "Analysis timed out"}
        )
    return JSONResponse(
        status_code=500,
        content={"success": False, "message": "Failed to send analyze command"}
    )


@app.get("/api/analysis")
async def getAnalysis():
    """Get latest scene analysis results"""
    try:
        if os.path.exists(ANALYSIS_FILE):
            with open(ANALYSIS_FILE, 'r') as f:
                return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"Error reading analysis: {e}")
    return {"success": False, "message": "No analysis available"}


@app.post("/api/webrtc/offer")
async def webrtcOffer(request: Request):
    """WebRTC signaling: accept offer, return answer"""
    if not WEBRTC_AVAILABLE:
        return JSONResponse(
            status_code=501,
            content={"error": "WebRTC not available (aiortc not installed)"}
        )

    params = await request.json()
    offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])

    # Configure ICE with a public STUN server for NAT traversal
    config = RTCConfiguration(
        iceServers=[RTCIceServer(urls=["stun:stun.l.google.com:19302"])]
    )
    pc = RTCPeerConnection(configuration=config)
    peerConnections.add(pc)

    @pc.on("connectionstatechange")
    async def onConnectionStateChange():
        if pc.connectionState in ("failed", "closed", "disconnected"):
            await pc.close()
            peerConnections.discard(pc)

    pc.addTrack(LiveCameraTrack())

    await pc.setRemoteDescription(offer)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    return {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}


@app.get("/api/webrtc/status")
async def webrtcStatus():
    """Check if WebRTC streaming is available"""
    return {"available": WEBRTC_AVAILABLE, "connections": len(peerConnections)}


@app.get("/api/videos")
async def apiVideos():
    """List all recorded videos"""
    return {"videos": listVideos()}


@app.get("/api/video/{filename}")
async def downloadVideo(filename: str):
    """Download a video file"""
    filepath = os.path.join(VIDEO_DIR, filename)
    
    # Security: prevent path traversal
    if ".." in filename or filename.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid filename")
    
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="File not found")
    
    return FileResponse(
        filepath,
        filename=filename,
        media_type="video/mp4"
    )


@app.get("/api/stream/{filename}")
async def streamVideo(filename: str, request: Request):
    """Stream video for preview (supports range requests)"""
    filepath = os.path.join(VIDEO_DIR, filename)
    
    # Security: prevent path traversal
    if ".." in filename or filename.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid filename")
    
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="File not found")
    
    fileSize = os.path.getsize(filepath)
    rangeHeader = request.headers.get("range")
    
    if rangeHeader:
        # Parse range header
        rangeMatch = rangeHeader.replace("bytes=", "").split("-")
        start = int(rangeMatch[0]) if rangeMatch[0] else 0
        end = int(rangeMatch[1]) if rangeMatch[1] else fileSize - 1
        
        if start >= fileSize:
            raise HTTPException(status_code=416, detail="Range not satisfiable")
        
        end = min(end, fileSize - 1)
        chunkSize = end - start + 1
        
        def iterFile():
            with open(filepath, "rb") as f:
                f.seek(start)
                remaining = chunkSize
                while remaining > 0:
                    readSize = min(8192, remaining)
                    data = f.read(readSize)
                    if not data:
                        break
                    remaining -= len(data)
                    yield data
        
        return StreamingResponse(
            iterFile(),
            status_code=206,
            media_type="video/mp4",
            headers={
                "Content-Range": f"bytes {start}-{end}/{fileSize}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(chunkSize)
            }
        )
    else:
        return FileResponse(filepath, media_type="video/mp4")


@app.delete("/api/video/{filename}")
async def deleteVideo(filename: str):
    """Delete a video file"""
    filepath = os.path.join(VIDEO_DIR, filename)
    
    # Security: prevent path traversal
    if ".." in filename or filename.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid filename")
    
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="File not found")
    
    try:
        os.remove(filepath)
        return {"success": True, "message": f"Deleted {filename}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.websocket("/ws")
async def websocketEndpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time status updates"""
    await websocket.accept()
    activeConnections.append(websocket)
    
    try:
        while True:
            # Send status every 2 seconds
            status = getStatus()
            await websocket.send_json(status)
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        activeConnections.remove(websocket)
    except Exception:
        if websocket in activeConnections:
            activeConnections.remove(websocket)


async def broadcastStatus():
    """Broadcast status to all connected WebSocket clients"""
    status = getStatus()
    for connection in activeConnections:
        try:
            await connection.send_json(status)
        except:
            pass


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=80)
