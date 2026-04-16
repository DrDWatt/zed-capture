#!/usr/bin/env python3
"""
ZED 2i Stereo Capture Service (Host Version)
Records SVO format with depth data using ZED SDK directly on host.
Supports dynamic camera settings via .settings JSON file.
"""

import os
import sys
import json
import time
import signal
import threading
import subprocess
from datetime import datetime
from pathlib import Path

from PIL import Image
import io

from camera_settings import (
    loadSettings, saveSettings, validateSettings, needsCameraRestart,
    DEFAULT_SETTINGS, SETTINGS_FILE, exposureToShutterSpeed,
    VALID_RESOLUTIONS, VALID_DEPTH_MODES, VALID_COMPRESSIONS
)

# Import ZED SDK - this runs on host, not in Docker
try:
    import pyzed.sl as sl
    ZED_AVAILABLE = True
    print("ZED SDK loaded successfully")
except (ImportError, OSError) as e:
    print("ZED SDK not available: {}".format(e))
    print("Falling back to GStreamer recording (no depth)")
    ZED_AVAILABLE = False
    sl = None

# Configuration - paths from env vars for Docker/host portability
VIDEO_OUTPUT_DIR = os.environ.get("VIDEO_DIR", "/mnt/videos")
CONTROL_FILE = os.path.join(VIDEO_OUTPUT_DIR, ".control")
STATUS_FILE = os.path.join(VIDEO_OUTPUT_DIR, ".status")
ANALYSIS_FILE = os.path.join(VIDEO_OUTPUT_DIR, ".analysis")
MAX_RECORDING_DURATION = 3600  # 1 hour max per file

# Target brightness range (0-255 scale)
TARGET_BRIGHTNESS_LOW = 100
TARGET_BRIGHTNESS_HIGH = 160
TARGET_BRIGHTNESS_IDEAL = 130
ANALYSIS_FRAME_COUNT = 10  # Number of frames to sample

# ZED camera model specifications
# Polarized lenses reduce light by ~1 stop (~50%), affecting exposure recommendations.
# Models with polarization need higher exposure/gain to compensate.
ZED_MODEL_SPECS = {
    "ZED": {
        "polarized": False,
        "lightLossFactor": 1.0,
        "lensType": "Standard",
        "hFov": 90,
        "minFocusDistance": 0.3,
        "notes": "No polarization filter"
    },
    "ZED Mini": {
        "polarized": False,
        "lightLossFactor": 1.0,
        "lensType": "Standard wide-angle",
        "hFov": 90,
        "minFocusDistance": 0.1,
        "notes": "No polarization filter"
    },
    "ZED 2": {
        "polarized": True,
        "lightLossFactor": 1.8,
        "lensType": "Polarized wide-angle",
        "hFov": 110,
        "minFocusDistance": 0.2,
        "notes": "Polarized lenses reduce ~1 stop; expect lower raw brightness"
    },
    "ZED 2i": {
        "polarized": True,
        "lightLossFactor": 1.8,
        "lensType": "Polarized wide-angle",
        "hFov": 110,
        "minFocusDistance": 0.2,
        "notes": "Polarized lenses reduce ~1 stop; reduces glare on reflective surfaces"
    },
    "ZED X": {
        "polarized": False,
        "lightLossFactor": 1.0,
        "lensType": "Global shutter",
        "hFov": 110,
        "minFocusDistance": 0.2,
        "notes": "No polarization filter; global shutter sensor"
    },
    "ZED X Mini": {
        "polarized": False,
        "lightLossFactor": 1.0,
        "lensType": "Global shutter compact",
        "hFov": 105,
        "minFocusDistance": 0.1,
        "notes": "No polarization filter; global shutter sensor"
    },
}
DEFAULT_MODEL_SPEC = ZED_MODEL_SPECS["ZED 2i"]

# SDK enum mappings
RESOLUTION_MAP = {}
DEPTH_MODE_MAP = {}
COMPRESSION_MAP = {}
if ZED_AVAILABLE:
    RESOLUTION_MAP = {
        "HD720": sl.RESOLUTION.HD720,
        "HD1080": sl.RESOLUTION.HD1080,
        "HD2K": sl.RESOLUTION.HD2K
    }
    DEPTH_MODE_MAP = {
        "NEURAL": sl.DEPTH_MODE.NEURAL,
        "ULTRA": sl.DEPTH_MODE.ULTRA,
        "QUALITY": sl.DEPTH_MODE.QUALITY,
        "PERFORMANCE": sl.DEPTH_MODE.PERFORMANCE,
        "NONE": sl.DEPTH_MODE.NONE
    }
    COMPRESSION_MAP = {
        "H264": sl.SVO_COMPRESSION_MODE.H264,
        "H265": sl.SVO_COMPRESSION_MODE.H265,
        "H264_LOSSLESS": sl.SVO_COMPRESSION_MODE.H264_LOSSLESS,
        "H265_LOSSLESS": sl.SVO_COMPRESSION_MODE.H265_LOSSLESS
    }

class CaptureService:
    def __init__(self):
        self.recording = False
        self.recordingThread = None
        self.stopEvent = threading.Event()
        self.currentFilename = None
        self.zed = None
        self.runtimeParams = None
        self.settings = loadSettings()
        self.settingsMtime = 0
        self._liveFramePath = os.path.join(VIDEO_OUTPUT_DIR, ".live_frame.jpg")
        self._liveImage = None
        self._liveFrameCount = 0
        self.cameraModel = "Unknown"
        self.modelSpec = DEFAULT_MODEL_SPEC
        
        # Ensure output directory exists
        Path(VIDEO_OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
        
        # Initialize status
        self.updateStatus("idle", "Service started")
        
    def initCamera(self):
        """Initialize ZED camera with current settings"""
        for dev in ['/dev/video0', '/dev/video1']:
            if os.path.exists(dev):
                print("Found video device: {}".format(dev))
                break
        
        if ZED_AVAILABLE:
            try:
                self.zed = sl.Camera()
                initParams = sl.InitParameters()
                initParams.camera_resolution = RESOLUTION_MAP.get(
                    self.settings["resolution"], sl.RESOLUTION.HD1080)
                initParams.camera_fps = 30
                initParams.depth_mode = DEPTH_MODE_MAP.get(
                    self.settings["depthMode"], sl.DEPTH_MODE.NEURAL)
                initParams.depth_minimum_distance = 0.3
                initParams.coordinate_units = sl.UNIT.METER
                initParams.sdk_verbose = 1
                
                print("Opening ZED camera with SDK...")
                err = self.zed.open(initParams)
                
                if err == sl.ERROR_CODE.SUCCESS:
                    self.runtimeParams = sl.RuntimeParameters()
                    self._liveImage = sl.Mat()
                    self.applyLiveSettings()
                    self._detectCameraModel()
                    self.logCameraInfo()
                    saveSettings(self.settings)
                    return True
                else:
                    print("ZED SDK open failed: {}".format(err))
                    self.zed = None
            except Exception as e:
                print("ZED SDK exception: {}".format(e))
                self.zed = None
        
        print("Using GStreamer/V4L2 for video capture (no depth)")
        return True
    
    def _detectCameraModel(self):
        """Detect camera model from SDK and load its specifications"""
        if not self.zed:
            return
        info = self.zed.get_camera_information()
        modelStr = str(info.camera_model)
        print("  Raw camera model enum: {}".format(modelStr))
        # SDK returns strings like "ZED 2i", "ZED 2", "ZED", "ZED X Mini" etc.
        # Check specific/longer names first to avoid "ZED" matching prematurely
        modelMap = [
            ("ZED X Mini", "ZED X Mini"),
            ("ZED X", "ZED X"),
            ("ZED 2i", "ZED 2i"),
            ("ZED 2", "ZED 2"),
            ("ZED Mini", "ZED Mini"),
            ("ZED", "ZED"),
        ]
        for matchStr, specKey in modelMap:
            if matchStr in modelStr:
                self.cameraModel = specKey
                self.modelSpec = ZED_MODEL_SPECS.get(specKey, DEFAULT_MODEL_SPEC)
                return
        # Fallback: use the raw string as model name
        self.cameraModel = modelStr
        self.modelSpec = DEFAULT_MODEL_SPEC

    def logCameraInfo(self):
        """Log current camera state"""
        if not self.zed:
            return
        info = self.zed.get_camera_information()
        res = info.camera_configuration.resolution
        s = self.settings
        spec = self.modelSpec
        print("ZED SDK initialized: {}".format(self.cameraModel))
        print("  Serial: {}".format(info.serial_number))
        print("  Lens: {} | Polarized: {}".format(
            spec["lensType"], "YES" if spec["polarized"] else "NO"))
        if spec["polarized"]:
            print("  Light loss factor: {:.1f}x ({})".format(
                spec["lightLossFactor"], spec["notes"]))
        print("  Resolution: {}x{} @ 30 FPS".format(res.width, res.height))
        print("  Depth mode: {}, min distance: 0.3m".format(s["depthMode"]))
        print("  Compression: {}".format(s["compression"]))
        autoExp = "ON" if s["autoExposure"] else "OFF"
        print("  Auto exposure: {}".format(autoExp))
        if not s["autoExposure"]:
            print("  Exposure: {} ({})".format(
                s["exposure"], exposureToShutterSpeed(s["exposure"])))
            print("  Gain: {}".format(s["gain"]))
        autoWb = "ON" if s["autoWhiteBalance"] else "OFF"
        print("  Auto white balance: {}".format(autoWb))
        if not s["autoWhiteBalance"]:
            print("  White balance: {}K".format(s["whiteBalance"]))
        print("  Brightness: {}".format(s["brightness"]))

    def applyLiveSettings(self):
        """Apply settings that can be changed without camera restart"""
        if not self.zed:
            return
        s = self.settings
        # Auto exposure/gain
        self.zed.set_camera_settings(
            sl.VIDEO_SETTINGS.AEC_AGC, 1 if s["autoExposure"] else 0)
        if not s["autoExposure"]:
            self.zed.set_camera_settings(sl.VIDEO_SETTINGS.EXPOSURE, s["exposure"])
            self.zed.set_camera_settings(sl.VIDEO_SETTINGS.GAIN, s["gain"])
        # Brightness
        self.zed.set_camera_settings(sl.VIDEO_SETTINGS.BRIGHTNESS, s["brightness"])
        # White balance
        self.zed.set_camera_settings(
            sl.VIDEO_SETTINGS.WHITEBALANCE_AUTO, 1 if s["autoWhiteBalance"] else 0)
        if not s["autoWhiteBalance"]:
            self.zed.set_camera_settings(
                sl.VIDEO_SETTINGS.WHITEBALANCE_TEMPERATURE, s["whiteBalance"])
        print("Camera settings applied")

    def handleSettingsChange(self):
        """Check for settings file changes and apply"""
        try:
            if not os.path.exists(SETTINGS_FILE):
                return
            mtime = os.path.getmtime(SETTINGS_FILE)
            if mtime <= self.settingsMtime:
                return
            self.settingsMtime = mtime
            newSettings = loadSettings()
            validated, errors = validateSettings(newSettings)
            if errors:
                print("Settings validation errors: {}".format(errors))
            
            if self.recording:
                print("Cannot change settings while recording")
                return
            
            oldSettings = self.settings
            self.settings = validated
            
            if needsCameraRestart(oldSettings, validated):
                print("Resolution/depth mode changed, restarting camera...")
                self.closeCamera()
                self.initCamera()
            else:
                self.applyLiveSettings()
                saveSettings(validated)
                self.logCameraInfo()
        except Exception as e:
            print("Error handling settings change: {}".format(e))
        
    def _writeLiveFrame(self):
        """Write current camera frame as JPEG for WebRTC live streaming"""
        if not self.zed or not self._liveImage:
            return
        try:
            self.zed.retrieve_image(self._liveImage, sl.VIEW.LEFT)
            frame = self._liveImage.get_data()
            if frame is None:
                return
            # BGRA -> RGB
            rgb = frame[:, :, [2, 1, 0]]
            img = Image.fromarray(rgb)
            img = img.resize((960, 540), Image.BILINEAR)
            tmpPath = self._liveFramePath + ".tmp"
            img.save(tmpPath, "JPEG", quality=70)
            os.replace(tmpPath, self._liveFramePath)
        except Exception:
            pass

    def closeCamera(self):
        """Close camera resources"""
        if self.zed:
            self.zed.close()
            self.zed = None
            self._liveImage = None
            print("ZED camera closed")
            
    def updateStatus(self, state, message, filename=None):
        """Update status file for web container to read"""
        status = {
            "state": state,
            "message": message,
            "timestamp": datetime.now().isoformat(),
            "filename": filename or ""
        }
        try:
            with open(STATUS_FILE, 'w') as f:
                f.write(f"{status['state']}|{status['message']}|{status['timestamp']}|{status['filename']}")
        except Exception as e:
            print(f"Error updating status: {e}")
            
    def generateFilename(self, extension="svo2"):
        """Generate timestamped filename"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"zed_capture_{timestamp}.{extension}"
        
    def recordWithGStreamer(self, filename):
        """Record using GStreamer pipeline (fallback, no depth)"""
        outputPath = os.path.join(VIDEO_OUTPUT_DIR, filename)
        res = self.settings.get("resolution", "HD1080")
        dims = {"HD720": "1280,720", "HD1080": "1920,1080", "HD2K": "2208,1242"}
        wxh = dims.get(res, "1920,1080").split(",")
        
        cmd = [
            "gst-launch-1.0", "-e",
            "v4l2src", "device=/dev/video0", "!",
            "videoconvert", "!",
            "videoscale", "!",
            "video/x-raw,width={},height={},framerate=30/1".format(wxh[0], wxh[1]), "!",
            "x264enc", "tune=zerolatency", "bitrate=4000", "speed-preset=ultrafast", "!",
            "video/x-h264,profile=baseline", "!",
            "mp4mux", "faststart=true", "!",
            "filesink", "location={}".format(outputPath)
        ]
        
        print("Starting GStreamer: {}".format(' '.join(cmd)), flush=True)
        return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
    def recordingLoop(self, filename):
        """Main recording loop using ZED SDK or GStreamer fallback"""
        self.currentFilename = filename
        outputPath = os.path.join(VIDEO_OUTPUT_DIR, filename)
        self.updateStatus("recording", f"Recording to {filename}", filename)
        
        startTime = time.time()
        frameCount = 0
        gstProc = None
        
        try:
            if self.zed:
                # ZED SDK recording with current compression setting
                recordingParams = sl.RecordingParameters()
                recordingParams.video_filename = outputPath
                compression = COMPRESSION_MAP.get(
                    self.settings["compression"], sl.SVO_COMPRESSION_MODE.H265)
                recordingParams.compression_mode = compression
                
                print("Starting SVO recording to: {}".format(outputPath))
                err = self.zed.enable_recording(recordingParams)
                
                if err != sl.ERROR_CODE.SUCCESS:
                    print("Failed to start recording: {}".format(err))
                    self.updateStatus("error", "Failed to start recording: {}".format(err))
                    return
                    
                print("Recording started (SVO {} with {} depth)".format(
                    self.settings["compression"], self.settings["depthMode"]))
                
                while not self.stopEvent.is_set():
                    if self.zed.grab(self.runtimeParams) == sl.ERROR_CODE.SUCCESS:
                        frameCount += 1
                        
                        # Write live frame every 2 grabs (~15fps at 30fps)
                        if frameCount % 2 == 0:
                            self._writeLiveFrame()
                        
                        elapsed = time.time() - startTime
                        if frameCount % 150 == 0:
                            print(f"Recording: {elapsed:.1f}s, {frameCount} frames")
                            
                    if time.time() - startTime > MAX_RECORDING_DURATION:
                        print("Max recording duration reached")
                        break
                        
                self.zed.disable_recording()
                print("SVO recording stopped")
            else:
                # GStreamer fallback (MP4, no depth)
                gstProc = self.recordWithGStreamer(filename)
                
                while not self.stopEvent.is_set():
                    if gstProc.poll() is not None:
                        print("GStreamer process ended unexpectedly")
                        break
                    if time.time() - startTime > MAX_RECORDING_DURATION:
                        print("Max recording duration reached")
                        break
                    time.sleep(0.5)
                    
                if gstProc and gstProc.poll() is None:
                    gstProc.send_signal(signal.SIGINT)
                    try:
                        stdout, stderr = gstProc.communicate(timeout=10)
                        if stderr:
                            print(f"GStreamer: {stderr.decode()}", flush=True)
                    except subprocess.TimeoutExpired:
                        gstProc.kill()
                        gstProc.wait()
                    
        except Exception as e:
            print(f"Recording error: {e}")
            self.updateStatus("error", str(e))
        finally:
            if gstProc and gstProc.poll() is None:
                try:
                    gstProc.kill()
                    gstProc.wait()
                except:
                    pass
            
            if os.path.exists(outputPath):
                size = os.path.getsize(outputPath)
                sizeMb = size / (1024 * 1024)
                print(f"Video saved: {outputPath} ({sizeMb:.1f} MB)")
            else:
                print(f"WARNING: Video file not created: {outputPath}")
                    
        duration = time.time() - startTime
        self.updateStatus("idle", f"Recording complete: {filename} ({duration:.1f}s)", filename)
        self.recording = False
        self.currentFilename = None
        
        # Auto-generate MP4 preview for SVO files
        if os.path.exists(outputPath) and (outputPath.endswith('.svo') or outputPath.endswith('.svo2')):
            self.spawnPreviewConversion(outputPath)
        
    def analyzeScene(self):
        """Grab sample frames and analyze brightness to recommend settings"""
        if not self.zed:
            self.writeAnalysis({
                "success": False,
                "error": "Camera not available",
                "timestamp": datetime.now().isoformat()
            })
            return False

        if self.recording:
            self.writeAnalysis({
                "success": False,
                "error": "Cannot analyze while recording",
                "timestamp": datetime.now().isoformat()
            })
            return False

        print("Analyzing scene...")
        self.updateStatus("analyzing", "Analyzing scene brightness")

        try:
            import numpy as np
        except ImportError:
            self.writeAnalysis({
                "success": False,
                "error": "numpy not available for analysis",
                "timestamp": datetime.now().isoformat()
            })
            self.updateStatus("idle", "Analysis failed: numpy missing")
            return False

        image = sl.Mat()
        brightnessSamples = []
        channelMeans = {"r": [], "g": [], "b": []}

        # Grab multiple frames for stable measurement
        for i in range(ANALYSIS_FRAME_COUNT + 5):
            err = self.zed.grab(self.runtimeParams)
            if err != sl.ERROR_CODE.SUCCESS:
                continue
            # Skip first 5 frames to let auto-exposure settle
            if i < 5:
                continue
            self.zed.retrieve_image(image, sl.VIEW.LEFT)
            frame = image.get_data()
            if frame is None:
                continue
            # frame is BGRA
            b, g, r = frame[:,:,0], frame[:,:,1], frame[:,:,2]
            gray = 0.299 * r + 0.587 * g + 0.114 * b
            brightnessSamples.append(float(np.mean(gray)))
            channelMeans["r"].append(float(np.mean(r)))
            channelMeans["g"].append(float(np.mean(g)))
            channelMeans["b"].append(float(np.mean(b)))

        if not brightnessSamples:
            self.writeAnalysis({
                "success": False,
                "error": "Could not grab frames",
                "timestamp": datetime.now().isoformat()
            })
            self.updateStatus("idle", "Analysis failed: no frames")
            return False

        avgBrightness = sum(brightnessSamples) / len(brightnessSamples)
        avgR = sum(channelMeans["r"]) / len(channelMeans["r"])
        avgG = sum(channelMeans["g"]) / len(channelMeans["g"])
        avgB = sum(channelMeans["b"]) / len(channelMeans["b"])

        # Read current camera settings
        curExposure = self.settings.get("exposure", 75)
        curGain = self.settings.get("gain", 40)
        curBrightness = self.settings.get("brightness", 5)
        curWb = self.settings.get("whiteBalance", 4500)
        curAutoExp = self.settings.get("autoExposure", False)
        curAutoWb = self.settings.get("autoWhiteBalance", False)

        # Adjust brightness targets for polarized lenses.
        # Polarized lenses absorb ~1 stop of light, so raw readings
        # will be inherently lower. We lower the thresholds accordingly
        # so the analysis doesn't falsely flag a well-lit polarized scene
        # as "too dark".
        spec = self.modelSpec
        lightLoss = spec["lightLossFactor"]
        adjustedLow = TARGET_BRIGHTNESS_LOW / lightLoss
        adjustedHigh = TARGET_BRIGHTNESS_HIGH / lightLoss
        adjustedIdeal = TARGET_BRIGHTNESS_IDEAL / lightLoss

        # Compute recommended exposure/gain with polarization compensation
        rec = self.computeRecommendedSettings(
            avgBrightness, avgR, avgG, avgB,
            curExposure, curGain, curBrightness, curWb,
            adjustedLow, adjustedHigh, adjustedIdeal
        )

        # Build verdict using polarization-adjusted thresholds
        if avgBrightness < adjustedLow:
            verdict = "TOO_DARK"
            verdictText = "Scene is too dark (avg {:.0f}/255)".format(avgBrightness)
            if spec["polarized"]:
                verdictText += " \u2014 polarized lenses reduce ~1 stop"
        elif avgBrightness > adjustedHigh:
            verdict = "TOO_BRIGHT"
            verdictText = "Scene is too bright (avg {:.0f}/255)".format(avgBrightness)
        else:
            verdict = "OK"
            verdictText = "Scene brightness is acceptable (avg {:.0f}/255)".format(avgBrightness)
            if spec["polarized"]:
                verdictText += " (adjusted for polarized lenses)"

        analysis = {
            "success": True,
            "timestamp": datetime.now().isoformat(),
            "camera": {
                "model": self.cameraModel,
                "polarized": spec["polarized"],
                "lensType": spec["lensType"],
                "lightLossFactor": lightLoss,
                "hFov": spec["hFov"],
                "notes": spec["notes"]
            },
            "measured": {
                "avgBrightness": round(avgBrightness, 1),
                "avgR": round(avgR, 1),
                "avgG": round(avgG, 1),
                "avgB": round(avgB, 1),
                "samples": len(brightnessSamples)
            },
            "brightnessTargets": {
                "low": round(adjustedLow, 1),
                "high": round(adjustedHigh, 1),
                "ideal": round(adjustedIdeal, 1),
                "polarizationAdjusted": spec["polarized"]
            },
            "verdict": verdict,
            "verdictText": verdictText,
            "current": {
                "autoExposure": curAutoExp,
                "exposure": curExposure,
                "gain": curGain,
                "brightness": curBrightness,
                "autoWhiteBalance": curAutoWb,
                "whiteBalance": curWb
            },
            "recommended": rec
        }

        self.writeAnalysis(analysis)
        print("Analysis complete: {} (brightness={:.0f})".format(verdict, avgBrightness))
        print("  Recommended: exposure={}, gain={}, brightness={}, wb={}K".format(
            rec["exposure"], rec["gain"], rec["brightness"], rec["whiteBalance"]))
        self.updateStatus("idle", "Analysis complete: {}".format(verdictText))
        return True

    def computeRecommendedSettings(self, avgBrightness, avgR, avgG, avgB,
                                    curExposure, curGain, curBrightness, curWb,
                                    targetLow=None, targetHigh=None,
                                    targetIdeal=None):
        """Compute recommended camera settings based on measured brightness.
        Targets are adjusted for polarized lenses when applicable."""
        if targetLow is None:
            targetLow = TARGET_BRIGHTNESS_LOW
        if targetHigh is None:
            targetHigh = TARGET_BRIGHTNESS_HIGH
        if targetIdeal is None:
            targetIdeal = TARGET_BRIGHTNESS_IDEAL

        recExposure = curExposure
        recGain = curGain
        recBrightness = curBrightness
        recWb = curWb

        if avgBrightness < targetLow:
            # Scene is too dark - increase exposure first, then gain
            ratio = targetIdeal / max(avgBrightness, 1)
            # Scale exposure proportionally
            recExposure = min(100, int(curExposure * ratio))
            # If exposure maxed out, boost gain
            if recExposure >= 100:
                recExposure = 100
                remainingRatio = ratio / (100.0 / max(curExposure, 1))
                recGain = min(100, int(curGain * remainingRatio))
                if recGain < 20:
                    recGain = 20
            # Bump brightness if still very dark
            if avgBrightness < (targetLow * 0.6):
                recBrightness = min(8, curBrightness + 2)
            elif avgBrightness < targetLow:
                recBrightness = min(8, curBrightness + 1)

        elif avgBrightness > targetHigh:
            # Scene is too bright - reduce exposure
            ratio = targetIdeal / max(avgBrightness, 1)
            recExposure = max(1, int(curExposure * ratio))
            recGain = max(0, int(curGain * ratio))
            if avgBrightness > (targetHigh * 1.25):
                recBrightness = max(0, curBrightness - 2)

        # Estimate color temperature from R/B ratio
        if avgB > 0:
            rbRatio = avgR / avgB
            # Rough mapping: rbRatio < 1 = cool/blue, > 1 = warm/orange
            if rbRatio < 0.85:
                recWb = min(6500, curWb + 500)  # Too blue, warm it up
            elif rbRatio > 1.3:
                recWb = max(2800, curWb - 500)  # Too warm, cool it down
            # Snap to nearest 100
            recWb = int(round(recWb / 100.0) * 100)

        return {
            "autoExposure": False,
            "exposure": recExposure,
            "gain": recGain,
            "brightness": recBrightness,
            "autoWhiteBalance": False,
            "whiteBalance": recWb
        }

    def writeAnalysis(self, data):
        """Write analysis results to shared file for web server"""
        try:
            with open(ANALYSIS_FILE, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print("Error writing analysis: {}".format(e))

    def spawnPreviewConversion(self, svoPath):
        """Spawn background process to convert SVO to MP4 preview"""
        scriptDir = os.path.dirname(os.path.abspath(__file__))
        script = os.path.join(scriptDir, "svo_to_mp4.py")
        if os.path.exists(script) and (svoPath.endswith('.svo') or svoPath.endswith('.svo2')):
            print(f"Starting background preview conversion for {os.path.basename(svoPath)}")
            env = dict(os.environ)
            subprocess.Popen(
                ["/usr/bin/python3", script, svoPath],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env
            )

    def startRecording(self):
        """Start a new recording"""
        if self.recording:
            print("Already recording")
            return False
            
        self.recording = True
        self.stopEvent.clear()
        
        # Use SVO for ZED SDK (includes depth), MP4 for GStreamer fallback
        if self.zed:
            filename = self.generateFilename("svo2")
        else:
            filename = self.generateFilename("mp4")
        self.recordingThread = threading.Thread(
            target=self.recordingLoop,
            args=(filename,)
        )
        self.recordingThread.start()
        return True
        
    def stopRecording(self):
        """Stop current recording"""
        if not self.recording:
            print("Not recording")
            return False
            
        self.stopEvent.set()
        if self.recordingThread:
            self.recordingThread.join(timeout=10)
        return True
        
    def processCommand(self, command):
        """Process control command"""
        command = command.strip().lower()
        
        if command == "start":
            return self.startRecording()
        elif command == "stop":
            return self.stopRecording()
        elif command == "analyze":
            return self.analyzeScene()
        elif command == "status":
            return True
        else:
            print(f"Unknown command: {command}")
            return False
            
    def run(self):
        """Main service loop"""
        print("ZED Capture Service (Host) starting...")
        print(f"Output directory: {VIDEO_OUTPUT_DIR}")
        
        # Initialize camera
        if not self.initCamera():
            print("WARNING: Running without camera")
            return
            
        print("Watching control file: {}".format(CONTROL_FILE))
        
        lastMtime = 0
        pollCount = 0
        
        try:
            while True:
                # Check control file and settings every ~0.5s (every 8 iterations)
                if pollCount % 8 == 0:
                    try:
                        if os.path.exists(CONTROL_FILE):
                            mtime = os.path.getmtime(CONTROL_FILE)
                            if mtime > lastMtime:
                                lastMtime = mtime
                                with open(CONTROL_FILE, 'r') as f:
                                    command = f.read().strip()
                                if command:
                                    print("Received command: {}".format(command))
                                    self.processCommand(command)
                    except Exception as e:
                        print("Error reading control file: {}".format(e))
                    self.handleSettingsChange()
                
                # Grab live frame when not recording (~15fps)
                if not self.recording and self.zed:
                    if self.zed.grab(self.runtimeParams) == sl.ERROR_CODE.SUCCESS:
                        self._writeLiveFrame()
                
                pollCount += 1
                time.sleep(1.0 / 15)  # ~15fps live frame rate
                
        except KeyboardInterrupt:
            print("\nShutting down...")
        finally:
            self.stopRecording()
            self.closeCamera()
            

if __name__ == "__main__":
    service = CaptureService()
    service.run()
