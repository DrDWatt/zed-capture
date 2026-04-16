#!/usr/bin/env python3
"""
ZED 2i Stereo Capture Service
Listens for control commands via a shared file-based protocol.
Records stereo video from ZED 2i camera to MP4 files.
"""

import os
import sys
import time
import signal
import threading
import subprocess
from datetime import datetime
from pathlib import Path

# ZED SDK disabled - causes EGL crashes in Docker on Jetson
# To enable: set USE_ZED_SDK=1 environment variable
import os
USE_ZED_SDK = os.environ.get("USE_ZED_SDK", "0") == "1"

if USE_ZED_SDK:
    try:
        import pyzed.sl as sl
        ZED_AVAILABLE = True
        print("ZED SDK module loaded")
    except ImportError as e:
        print(f"ZED SDK not available: {e}")
        ZED_AVAILABLE = False
        sl = None
else:
    print("Using GStreamer mode (ZED SDK disabled)")
    ZED_AVAILABLE = False
    sl = None

# Configuration
VIDEO_OUTPUT_DIR = "/mnt/videos"
CONTROL_FILE = "/mnt/videos/.control"
STATUS_FILE = "/mnt/videos/.status"
MAX_RECORDING_DURATION = 3600  # 1 hour max per file

class CaptureService:
    def __init__(self):
        self.recording = False
        self.recording_thread = None
        self.stop_event = threading.Event()
        self.current_filename = None
        self.zed = None
        self.runtime_params = None
        
        # Ensure output directory exists
        Path(VIDEO_OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
        
        # Initialize status
        self.updateStatus("idle", "Service started")
        
    def initCamera(self):
        """Initialize ZED camera with SDK or fallback to V4L2/GStreamer"""
        # First check for video devices
        videoDevice = None
        for dev in ['/dev/video0', '/dev/video1']:
            if os.path.exists(dev):
                videoDevice = dev
                print(f"Found video device: {dev}")
                break
        
        if not videoDevice:
            print("Warning: No video device found")
        
        # Try ZED SDK if available
        if ZED_AVAILABLE and sl:
            try:
                self.zed = sl.Camera()
                
                init_params = sl.InitParameters()
                init_params.camera_resolution = sl.RESOLUTION.HD720
                init_params.camera_fps = 30
                init_params.depth_mode = sl.DEPTH_MODE.PERFORMANCE
                init_params.coordinate_units = sl.UNIT.METER
                init_params.sdk_verbose = 0
                
                print("Attempting ZED SDK initialization...")
                err = self.zed.open(init_params)
                
                if err == sl.ERROR_CODE.SUCCESS:
                    self.runtime_params = sl.RuntimeParameters()
                    info = self.zed.get_camera_information()
                    print(f"ZED SDK initialized: {info.camera_model}")
                    print(f"  Serial: {info.serial_number}")
                    return True
                else:
                    print(f"ZED SDK failed: {err}")
                    self.zed = None
            except Exception as e:
                print(f"ZED SDK exception: {e}")
                self.zed = None
        
        # Fallback to GStreamer
        print("Using GStreamer/V4L2 for video capture")
        return True
        
    def closeCamera(self):
        """Close camera resources"""
        if self.zed and ZED_AVAILABLE:
            self.zed.close()
            self.zed = None
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
            
    def generateFilename(self, extension="svo"):
        """Generate timestamped filename"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"zed_capture_{timestamp}.{extension}"
        
    def recordWithGStreamer(self, filename):
        """Record using GStreamer pipeline"""
        output_path = os.path.join(VIDEO_OUTPUT_DIR, filename)
        
        # GStreamer pipeline for ZED camera
        # Use x264enc for browser/QuickTime compatible H.264 output
        cmd = [
            "gst-launch-1.0", "-e",
            "v4l2src", "device=/dev/video0", "!",
            "videoconvert", "!",
            "videoscale", "!",
            "video/x-raw,width=1280,height=720,framerate=30/1", "!",
            "x264enc", "tune=zerolatency", "bitrate=4000", "speed-preset=ultrafast", "!",
            "video/x-h264,profile=baseline", "!",
            "mp4mux", "faststart=true", "!",
            "filesink", f"location={output_path}"
        ]
        
        print(f"Starting GStreamer: {' '.join(cmd)}", flush=True)
        return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
    def recordWithZedSDK(self, filename):
        """Record using ZED SDK directly to SVO format (includes depth)"""
        output_path = os.path.join(VIDEO_OUTPUT_DIR, filename)
        
        if not ZED_AVAILABLE or not self.zed:
            print("ZED SDK not available for recording")
            return None
            
        # Configure recording - SVO format preserves stereo + depth
        recording_params = sl.RecordingParameters()
        recording_params.video_filename = output_path
        recording_params.compression_mode = sl.SVO_COMPRESSION_MODE.H264
        
        print(f"Starting ZED recording to: {output_path}")
        err = self.zed.enable_recording(recording_params)
        if err != sl.ERROR_CODE.SUCCESS:
            print(f"Failed to start recording: {err}")
            return None
        
        print("ZED recording enabled")
        return True
        
    def recordingLoop(self, filename):
        """Main recording loop"""
        self.current_filename = filename
        self.updateStatus("recording", f"Recording to {filename}", filename)
        
        start_time = time.time()
        gst_proc = None
        
        try:
            if ZED_AVAILABLE and self.zed:
                # Use ZED SDK recording
                if not self.recordWithZedSDK(filename):
                    self.updateStatus("error", "Failed to start ZED recording")
                    return
                    
                image = sl.Mat()
                while not self.stop_event.is_set():
                    if self.zed.grab(self.runtime_params) == sl.ERROR_CODE.SUCCESS:
                        self.zed.retrieve_image(image, sl.VIEW.SIDE_BY_SIDE)
                        
                    # Check max duration
                    if time.time() - start_time > MAX_RECORDING_DURATION:
                        print("Max recording duration reached")
                        break
                        
                    time.sleep(0.001)
                    
                self.zed.disable_recording()
            else:
                # Use GStreamer fallback
                gst_proc = self.recordWithGStreamer(filename)
                
                while not self.stop_event.is_set():
                    if gst_proc.poll() is not None:
                        print("GStreamer process ended unexpectedly")
                        break
                        
                    # Check max duration
                    if time.time() - start_time > MAX_RECORDING_DURATION:
                        print("Max recording duration reached")
                        break
                        
                    time.sleep(0.5)
                    
                if gst_proc and gst_proc.poll() is None:
                    # Send SIGINT for graceful EOS
                    gst_proc.send_signal(signal.SIGINT)
                    try:
                        stdout, stderr = gst_proc.communicate(timeout=10)
                        print(f"GStreamer stdout: {stdout.decode()}", flush=True)
                        print(f"GStreamer stderr: {stderr.decode()}", flush=True)
                    except subprocess.TimeoutExpired:
                        gst_proc.kill()
                        gst_proc.wait()
                    
        except Exception as e:
            print(f"Recording error: {e}")
            self.updateStatus("error", str(e))
        finally:
            if gst_proc and gst_proc.poll() is None:
                try:
                    gst_proc.kill()
                    gst_proc.wait()
                except:
                    pass
            
            # Verify file was created
            output_path = os.path.join(VIDEO_OUTPUT_DIR, filename)
            if os.path.exists(output_path):
                size = os.path.getsize(output_path)
                print(f"Video saved: {output_path} ({size} bytes)", flush=True)
            else:
                print(f"WARNING: Video file not created: {output_path}", flush=True)
                    
        duration = time.time() - start_time
        self.updateStatus("idle", f"Recording complete: {filename} ({duration:.1f}s)", filename)
        self.recording = False
        self.current_filename = None
        
    def startRecording(self):
        """Start a new recording"""
        if self.recording:
            print("Already recording")
            return False
            
        self.recording = True
        self.stop_event.clear()
        
        # Use SVO for ZED SDK (includes depth), MP4 for GStreamer fallback
        if ZED_AVAILABLE and self.zed:
            filename = self.generateFilename("svo")
        else:
            filename = self.generateFilename("mp4")
            
        self.recording_thread = threading.Thread(
            target=self.recordingLoop,
            args=(filename,)
        )
        self.recording_thread.start()
        return True
        
    def stopRecording(self):
        """Stop current recording"""
        if not self.recording:
            print("Not recording")
            return False
            
        self.stop_event.set()
        if self.recording_thread:
            self.recording_thread.join(timeout=10)
        return True
        
    def processCommand(self, command):
        """Process control command"""
        command = command.strip().lower()
        
        if command == "start":
            return self.startRecording()
        elif command == "stop":
            return self.stopRecording()
        elif command == "status":
            return True
        else:
            print(f"Unknown command: {command}")
            return False
            
    def run(self):
        """Main service loop"""
        print("ZED Capture Service starting...")
        
        # Initialize camera
        if not self.initCamera():
            print("Warning: Running without camera")
            
        print(f"Watching control file: {CONTROL_FILE}")
        print(f"Video output directory: {VIDEO_OUTPUT_DIR}")
        
        last_mtime = 0
        
        try:
            while True:
                # Check for control file changes
                try:
                    if os.path.exists(CONTROL_FILE):
                        mtime = os.path.getmtime(CONTROL_FILE)
                        if mtime > last_mtime:
                            last_mtime = mtime
                            with open(CONTROL_FILE, 'r') as f:
                                command = f.read().strip()
                            if command:
                                print(f"Received command: {command}")
                                self.processCommand(command)
                except Exception as e:
                    print(f"Error reading control file: {e}")
                    
                time.sleep(0.5)
                
        except KeyboardInterrupt:
            print("\nShutting down...")
        finally:
            self.stopRecording()
            self.closeCamera()
            

if __name__ == "__main__":
    service = CaptureService()
    service.run()
