#!/usr/bin/env python3
"""
Camera settings management for ZED capture service.
Handles reading/writing settings JSON and validation.
"""

import json
import os

VIDEO_DIR = os.environ.get("VIDEO_DIR", "/mnt/videos")
SETTINGS_FILE = os.path.join(VIDEO_DIR, ".settings")

# Default camera settings
DEFAULT_SETTINGS = {
    "resolution": "HD1080",
    "depthMode": "ULTRA",
    "autoExposure": False,
    "exposure": 75,
    "gain": 40,
    "autoWhiteBalance": False,
    "whiteBalance": 4500,
    "brightness": 5,
    "compression": "H265"
}

# Valid options for each setting
VALID_RESOLUTIONS = ["HD720", "HD1080", "HD2K"]
VALID_DEPTH_MODES = ["NEURAL", "ULTRA", "QUALITY", "PERFORMANCE", "NONE"]
VALID_COMPRESSIONS = ["H264", "H265", "H264_LOSSLESS", "H265_LOSSLESS"]

# Resolution dimensions for display
RESOLUTION_INFO = {
    "HD720": {"width": 1280, "height": 720, "maxFps": 60},
    "HD1080": {"width": 1920, "height": 1080, "maxFps": 30},
    "HD2K": {"width": 2208, "height": 1242, "maxFps": 15}
}

# Exposure value to approximate shutter speed mapping (at 30fps)
# SDK exposure 0-100 maps linearly to 0-33333µs at 30fps
def exposureToShutterSpeed(exposureValue, fps=30):
    """Convert SDK exposure value (0-100) to shutter speed string"""
    maxExposureUs = 1000000.0 / fps
    exposureUs = (exposureValue / 100.0) * maxExposureUs
    if exposureUs <= 0:
        return "0µs"
    shutterFraction = 1000000.0 / exposureUs
    if shutterFraction >= 1:
        return "1/{:.0f}s ({:.0f}µs)".format(shutterFraction, exposureUs)
    return "{:.0f}µs".format(exposureUs)


def loadSettings():
    """Load settings from file, return defaults if not found"""
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, 'r') as f:
                saved = json.load(f)
            # Merge with defaults to handle missing keys
            settings = dict(DEFAULT_SETTINGS)
            settings.update(saved)
            return settings
    except (json.JSONDecodeError, IOError) as e:
        print("Error loading settings: {}".format(e))
    return dict(DEFAULT_SETTINGS)


def saveSettings(settings):
    """Save settings to file"""
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings, f, indent=2)
        return True
    except IOError as e:
        print("Error saving settings: {}".format(e))
        return False


def validateSettings(settings):
    """Validate settings values, return cleaned settings and list of errors"""
    errors = []
    cleaned = dict(DEFAULT_SETTINGS)

    if settings.get("resolution") in VALID_RESOLUTIONS:
        cleaned["resolution"] = settings["resolution"]
    else:
        errors.append("Invalid resolution: {}".format(settings.get("resolution")))

    if settings.get("depthMode") in VALID_DEPTH_MODES:
        cleaned["depthMode"] = settings["depthMode"]
    else:
        errors.append("Invalid depth mode: {}".format(settings.get("depthMode")))

    cleaned["autoExposure"] = bool(settings.get("autoExposure", False))

    exp = settings.get("exposure", 75)
    if isinstance(exp, (int, float)) and 0 <= exp <= 100:
        cleaned["exposure"] = int(exp)
    else:
        errors.append("Exposure must be 0-100")

    gain = settings.get("gain", 40)
    if isinstance(gain, (int, float)) and 0 <= gain <= 100:
        cleaned["gain"] = int(gain)
    else:
        errors.append("Gain must be 0-100")

    cleaned["autoWhiteBalance"] = bool(settings.get("autoWhiteBalance", False))

    wb = settings.get("whiteBalance", 4500)
    if isinstance(wb, (int, float)) and 2800 <= wb <= 6500:
        cleaned["whiteBalance"] = int(round(wb / 100.0) * 100)
    else:
        errors.append("White balance must be 2800-6500")

    brt = settings.get("brightness", 5)
    if isinstance(brt, (int, float)) and 0 <= brt <= 8:
        cleaned["brightness"] = int(brt)
    else:
        errors.append("Brightness must be 0-8")

    if settings.get("compression") in VALID_COMPRESSIONS:
        cleaned["compression"] = settings["compression"]
    else:
        errors.append("Invalid compression: {}".format(settings.get("compression")))

    return cleaned, errors


def needsCameraRestart(oldSettings, newSettings):
    """Check if settings change requires camera close/reopen"""
    return (oldSettings.get("resolution") != newSettings.get("resolution") or
            oldSettings.get("depthMode") != newSettings.get("depthMode"))
