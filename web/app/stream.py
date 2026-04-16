#!/usr/bin/env python3
"""
WebRTC live camera streaming track.
Reads JPEG frames written by the capture service and streams via WebRTC.
"""

import asyncio
import fractions
import io
import os
import time

import numpy as np
from PIL import Image
from av import VideoFrame
from aiortc import MediaStreamTrack

VIDEO_DIR = os.environ.get("VIDEO_DIR", "/mnt/videos")
LIVE_FRAME_PATH = os.path.join(VIDEO_DIR, ".live_frame.jpg")
STREAM_FPS = 15
STREAM_WIDTH = 960
STREAM_HEIGHT = 540


class LiveCameraTrack(MediaStreamTrack):
    """WebRTC video track that reads JPEG frames from shared volume"""
    kind = "video"

    def __init__(self):
        super().__init__()
        self._startTime = time.time()
        self._frameCount = 0
        self._lastMtime = 0
        self._cachedArr = np.zeros((STREAM_HEIGHT, STREAM_WIDTH, 3), dtype=np.uint8)
        self._timeBase = fractions.Fraction(1, STREAM_FPS)

    async def recv(self):
        """Called by aiortc to get the next video frame"""
        self._frameCount += 1

        # Pace frames at target FPS
        targetTime = self._startTime + self._frameCount / STREAM_FPS
        wait = targetTime - time.time()
        if wait > 0:
            await asyncio.sleep(wait)

        # Read latest JPEG from shared file
        try:
            if os.path.exists(LIVE_FRAME_PATH):
                mtime = os.path.getmtime(LIVE_FRAME_PATH)
                if mtime != self._lastMtime:
                    self._lastMtime = mtime
                    with open(LIVE_FRAME_PATH, 'rb') as f:
                        data = f.read()
                    if len(data) > 100:
                        img = Image.open(io.BytesIO(data))
                        self._cachedArr = np.array(img.convert("RGB"))
        except Exception:
            pass

        frame = VideoFrame.from_ndarray(self._cachedArr, format="rgb24")
        frame.pts = self._frameCount
        frame.time_base = self._timeBase
        return frame
