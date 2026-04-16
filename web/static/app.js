// ZED Capture Control - Frontend JavaScript

let ws = null;
let reconnectInterval = null;
let peerConnection = null;
let webrtcAvailable = false;

// Initialize WebSocket connection
function initWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;
    
    ws = new WebSocket(wsUrl);
    
    ws.onopen = function() {
        console.log('WebSocket connected');
        if (reconnectInterval) {
            clearInterval(reconnectInterval);
            reconnectInterval = null;
        }
    };
    
    ws.onmessage = function(event) {
        const status = JSON.parse(event.data);
        updateStatusDisplay(status);
    };
    
    ws.onclose = function() {
        console.log('WebSocket disconnected');
        // Try to reconnect every 3 seconds
        if (!reconnectInterval) {
            reconnectInterval = setInterval(function() {
                console.log('Attempting to reconnect...');
                initWebSocket();
            }, 3000);
        }
    };
    
    ws.onerror = function(error) {
        console.error('WebSocket error:', error);
    };
}

// Update status display
function updateStatusDisplay(status) {
    const indicator = document.getElementById('status-indicator');
    const stateEl = document.getElementById('status-state');
    const messageEl = document.getElementById('status-message');
    const timeEl = document.getElementById('status-time');
    
    // Update indicator
    indicator.className = 'status-indicator ' + (status.state === 'recording' ? 'recording' : 'idle');
    
    // Update text
    stateEl.textContent = status.state.toUpperCase();
    messageEl.textContent = status.message;
    timeEl.textContent = status.timestamp;
    
    // Update button states
    const btnStart = document.getElementById('btn-start');
    const btnStop = document.getElementById('btn-stop');
    
    if (status.state === 'recording') {
        btnStart.disabled = true;
        btnStart.style.opacity = '0.5';
        btnStop.disabled = false;
        btnStop.style.opacity = '1';
    } else {
        btnStart.disabled = false;
        btnStart.style.opacity = '1';
        btnStop.disabled = true;
        btnStop.style.opacity = '0.5';
    }
}

// Start recording
async function startRecording() {
    try {
        const response = await fetch('/api/start', { method: 'POST' });
        const data = await response.json();
        
        if (!data.success) {
            showNotification(data.message, 'error');
        } else {
            showNotification('Recording started', 'success');
        }
    } catch (error) {
        console.error('Error starting recording:', error);
        showNotification('Failed to start recording', 'error');
    }
}

// Stop recording
async function stopRecording() {
    try {
        const response = await fetch('/api/stop', { method: 'POST' });
        const data = await response.json();
        
        if (!data.success) {
            showNotification(data.message, 'error');
        } else {
            showNotification('Recording stopped', 'success');
            // Refresh video list after a short delay
            setTimeout(refreshVideos, 1000);
        }
    } catch (error) {
        console.error('Error stopping recording:', error);
        showNotification('Failed to stop recording', 'error');
    }
}

// Refresh video list
async function refreshVideos() {
    try {
        const response = await fetch('/api/videos');
        const data = await response.json();
        
        const container = document.getElementById('videos-list');
        
        if (data.videos.length === 0) {
            container.innerHTML = '<p class="no-videos">No recordings yet</p>';
            return;
        }
        
        container.innerHTML = data.videos.map(video => {
            const typeBadge = video.isSvo ? '<span class="badge badge-svo">SVO+Depth</span>' : '';
            const previewBtn = video.hasPreview
                ? `<button class="btn btn-small btn-preview" onclick="previewVideo('${video.previewName}')">Preview</button>`
                : `<button class="btn btn-small btn-preview" disabled title="Converting preview...">Converting...</button>`;
            return `
                <div class="video-item">
                    <div class="video-info">
                        <span class="video-name">${video.name} ${typeBadge}</span>
                        <span class="video-meta">${video.sizeFormatted} | ${video.modifiedFormatted}</span>
                    </div>
                    <div class="video-actions">
                        ${previewBtn}
                        <a href="/api/video/${video.name}" class="btn btn-small btn-download" download>Download</a>
                        <button class="btn btn-small btn-delete" onclick="deleteVideo('${video.name}')">Delete</button>
                    </div>
                </div>
            `;
        }).join('');
    } catch (error) {
        console.error('Error refreshing videos:', error);
        showNotification('Failed to refresh video list', 'error');
    }
}

// Delete video
async function deleteVideo(filename) {
    if (!confirm(`Delete ${filename}?`)) {
        return;
    }
    
    try {
        const response = await fetch(`/api/video/${filename}`, { method: 'DELETE' });
        const data = await response.json();
        
        if (data.success) {
            showNotification('Video deleted', 'success');
            refreshVideos();
        } else {
            showNotification('Failed to delete video', 'error');
        }
    } catch (error) {
        console.error('Error deleting video:', error);
        showNotification('Failed to delete video', 'error');
    }
}

// Show notification
function showNotification(message, type) {
    // Create notification element
    const notification = document.createElement('div');
    notification.className = `notification ${type}`;
    notification.textContent = message;
    notification.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        padding: 15px 25px;
        border-radius: 8px;
        color: white;
        font-weight: 600;
        z-index: 1000;
        animation: slideIn 0.3s ease;
        background: ${type === 'success' ? '#27ae60' : '#e74c3c'};
    `;
    
    document.body.appendChild(notification);
    
    // Remove after 3 seconds
    setTimeout(() => {
        notification.style.animation = 'slideOut 0.3s ease';
        setTimeout(() => notification.remove(), 300);
    }, 3000);
}

// Add animation styles
const style = document.createElement('style');
style.textContent = `
    @keyframes slideIn {
        from { transform: translateX(100%); opacity: 0; }
        to { transform: translateX(0); opacity: 1; }
    }
    @keyframes slideOut {
        from { transform: translateX(0); opacity: 1; }
        to { transform: translateX(100%); opacity: 0; }
    }
`;
document.head.appendChild(style);

// Preview video in modal
function previewVideo(filename) {
    const modal = document.getElementById('video-modal');
    const player = document.getElementById('video-player');
    const source = document.getElementById('video-source');
    const title = document.getElementById('modal-title');
    const downloadLink = document.getElementById('modal-download');
    
    // Set video source (use preview MP4 for streaming)
    source.src = `/api/stream/${filename}`;
    source.type = 'video/mp4';
    player.load();
    
    // Set title (show original name, not preview name)
    const displayName = filename.replace('_preview.mp4', '.svo');
    title.textContent = displayName;
    downloadLink.href = `/api/video/${displayName}`;
    
    // Show modal
    modal.style.display = 'flex';
    document.body.style.overflow = 'hidden';
}

// Close modal
function closeModal(event) {
    if (event && event.target !== event.currentTarget) return;
    
    const modal = document.getElementById('video-modal');
    const player = document.getElementById('video-player');
    
    // Stop video playback
    player.pause();
    player.currentTime = 0;
    
    // Hide modal
    modal.style.display = 'none';
    document.body.style.overflow = '';
}

// Handle escape key to close modal
document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
        closeModal();
    }
});

// --- Scene Analysis ---

async function analyzeScene() {
    const btn = document.getElementById('btn-analyze');
    const resultDiv = document.getElementById('analysis-result');
    
    btn.disabled = true;
    btn.textContent = 'Analyzing...';
    resultDiv.innerHTML = '<p class="analysis-loading">Grabbing frames and measuring brightness...</p>';
    resultDiv.style.display = 'block';
    
    try {
        const response = await fetch('/api/analyze', { method: 'POST' });
        const data = await response.json();
        
        if (data.success) {
            renderAnalysisResult(data, resultDiv);
        } else {
            resultDiv.innerHTML = '<p class="analysis-error">Analysis failed: ' + (data.error || data.message) + '</p>';
        }
    } catch (error) {
        console.error('Error analyzing scene:', error);
        resultDiv.innerHTML = '<p class="analysis-error">Failed to analyze scene</p>';
        showNotification('Scene analysis failed', 'error');
    }
    
    btn.disabled = false;
    btn.textContent = 'Analyze Scene';
}

function renderAnalysisResult(data, container) {
    const m = data.measured;
    const rec = data.recommended;
    const cur = data.current;
    const cam = data.camera || {};
    const targets = data.brightnessTargets || {};
    
    // Brightness bar color
    let barColor = '#27ae60'; // green
    if (data.verdict === 'TOO_DARK') barColor = '#e74c3c';
    else if (data.verdict === 'TOO_BRIGHT') barColor = '#f39c12';
    
    const brightnessPercent = Math.min(100, (m.avgBrightness / 255) * 100).toFixed(0);
    
    let html = '<div class="analysis-content">';
    
    // Camera info
    if (cam.model) {
        html += '<div class="analysis-camera-info">';
        html += '<strong>' + cam.model + '</strong>';
        html += ' &mdash; ' + (cam.lensType || 'Unknown lens');
        if (cam.polarized) {
            html += ' <span class="badge-polarized">Polarized</span>';
            html += ' <span class="analysis-note">(~' + cam.lightLossFactor.toFixed(1) + 'x light loss)</span>';
        }
        html += '</div>';
    }
    
    // Verdict
    html += '<div class="analysis-verdict verdict-' + data.verdict.toLowerCase().replace('_', '-') + '">';
    html += '<strong>' + data.verdictText + '</strong>';
    html += '</div>';
    
    // Brightness meter with adjusted target range
    var targetLeft = targets.low ? (targets.low / 255 * 100).toFixed(0) : '39';
    var targetWidth = targets.high ? ((targets.high - targets.low) / 255 * 100).toFixed(0) : '24';
    var targetTitle = targets.low
        ? 'Target range (' + targets.low.toFixed(0) + '-' + targets.high.toFixed(0) + ')'
        : 'Target range (100-160)';
    if (targets.polarizationAdjusted) {
        targetTitle += ' [adjusted for polarized lenses]';
    }
    
    html += '<div class="analysis-meter">';
    html += '<label>Scene Brightness</label>';
    html += '<div class="brightness-bar-bg">';
    html += '<div class="brightness-bar" style="width:' + brightnessPercent + '%;background:' + barColor + '"></div>';
    html += '<div class="brightness-target" style="left:' + targetLeft + '%;width:' + targetWidth + '%" title="' + targetTitle + '"></div>';
    html += '</div>';
    html += '<span class="brightness-label">' + m.avgBrightness.toFixed(0) + ' / 255</span>';
    html += '</div>';
    
    // RGB readout
    html += '<div class="analysis-rgb">';
    html += '<span class="rgb-chip" style="color:#e74c3c">R:' + m.avgR.toFixed(0) + '</span> ';
    html += '<span class="rgb-chip" style="color:#27ae60">G:' + m.avgG.toFixed(0) + '</span> ';
    html += '<span class="rgb-chip" style="color:#3498db">B:' + m.avgB.toFixed(0) + '</span>';
    html += '</div>';
    
    // Comparison table
    if (data.verdict !== 'OK') {
        html += '<table class="analysis-table">';
        html += '<tr><th>Setting</th><th>Current</th><th>Recommended</th></tr>';
        if (cur.exposure !== rec.exposure)
            html += '<tr><td>Exposure</td><td>' + cur.exposure + '</td><td class="rec-val">' + rec.exposure + '</td></tr>';
        if (cur.gain !== rec.gain)
            html += '<tr><td>Gain</td><td>' + cur.gain + '</td><td class="rec-val">' + rec.gain + '</td></tr>';
        if (cur.brightness !== rec.brightness)
            html += '<tr><td>Brightness</td><td>' + cur.brightness + '</td><td class="rec-val">' + rec.brightness + '</td></tr>';
        if (cur.whiteBalance !== rec.whiteBalance)
            html += '<tr><td>White Balance</td><td>' + cur.whiteBalance + 'K</td><td class="rec-val">' + rec.whiteBalance + 'K</td></tr>';
        html += '</table>';
        html += '<button class="btn btn-apply-rec" onclick="applyRecommended()">Apply Recommended</button>';
    }
    
    html += '</div>';
    container.innerHTML = html;
    
    // Store recommended settings for apply
    container.dataset.recommended = JSON.stringify(rec);
}

async function applyRecommended() {
    const resultDiv = document.getElementById('analysis-result');
    const recJson = resultDiv.dataset.recommended;
    if (!recJson) return;
    
    const rec = JSON.parse(recJson);
    
    // Update UI sliders to match recommended
    document.getElementById('set-auto-exposure').checked = false;
    document.getElementById('set-exposure').value = rec.exposure;
    document.getElementById('exposure-val').textContent = rec.exposure;
    document.getElementById('shutter-speed').textContent = exposureToShutter(rec.exposure);
    document.getElementById('set-gain').value = rec.gain;
    document.getElementById('gain-val').textContent = rec.gain;
    document.getElementById('set-brightness').value = rec.brightness;
    document.getElementById('brightness-val').textContent = rec.brightness;
    document.getElementById('set-auto-wb').checked = false;
    document.getElementById('set-wb').value = rec.whiteBalance;
    document.getElementById('wb-val').textContent = rec.whiteBalance + 'K';
    toggleManualExposure(true);
    toggleManualWb(true);
    
    // Apply to server
    await applySettings();
    showNotification('Recommended settings applied', 'success');
}

// --- Camera Settings ---

// Convert exposure value (0-100) to shutter speed string
function exposureToShutter(val) {
    const maxUs = 33333; // 1/30s at 30fps
    const us = (val / 100.0) * maxUs;
    if (us <= 0) return '';
    const frac = 1000000.0 / us;
    if (frac >= 1) return '~1/' + Math.round(frac) + 's';
    return Math.round(us) + '\u03bcs';
}

// Update range display values
function initSettingsListeners() {
    const exposureSlider = document.getElementById('set-exposure');
    const gainSlider = document.getElementById('set-gain');
    const brightnessSlider = document.getElementById('set-brightness');
    const wbSlider = document.getElementById('set-wb');
    const autoExpCheckbox = document.getElementById('set-auto-exposure');
    const autoWbCheckbox = document.getElementById('set-auto-wb');

    exposureSlider.addEventListener('input', function() {
        document.getElementById('exposure-val').textContent = this.value;
        document.getElementById('shutter-speed').textContent = exposureToShutter(parseInt(this.value));
    });
    gainSlider.addEventListener('input', function() {
        document.getElementById('gain-val').textContent = this.value;
    });
    brightnessSlider.addEventListener('input', function() {
        document.getElementById('brightness-val').textContent = this.value;
    });
    wbSlider.addEventListener('input', function() {
        document.getElementById('wb-val').textContent = this.value + 'K';
    });
    autoExpCheckbox.addEventListener('change', function() {
        toggleManualExposure(!this.checked);
    });
    autoWbCheckbox.addEventListener('change', function() {
        toggleManualWb(!this.checked);
    });
}

function toggleManualExposure(show) {
    document.getElementById('manual-exposure-group').style.display = show ? '' : 'none';
    document.getElementById('manual-gain-group').style.display = show ? '' : 'none';
}

function toggleManualWb(show) {
    document.getElementById('manual-wb-group').style.display = show ? '' : 'none';
}

// Load settings from server and populate UI
async function loadSettings() {
    try {
        const response = await fetch('/api/settings');
        const s = await response.json();

        document.getElementById('set-resolution').value = s.resolution || 'HD1080';
        document.getElementById('set-depth').value = s.depthMode || 'NEURAL';
        document.getElementById('set-compression').value = s.compression || 'H265';
        document.getElementById('set-brightness').value = s.brightness || 5;
        document.getElementById('brightness-val').textContent = s.brightness || 5;

        document.getElementById('set-auto-exposure').checked = !!s.autoExposure;
        var exp = s.exposure || 75;
        document.getElementById('set-exposure').value = exp;
        document.getElementById('exposure-val').textContent = exp;
        document.getElementById('shutter-speed').textContent = exposureToShutter(exp);
        document.getElementById('set-gain').value = s.gain || 40;
        document.getElementById('gain-val').textContent = s.gain || 40;

        document.getElementById('set-auto-wb').checked = !!s.autoWhiteBalance;
        document.getElementById('set-wb').value = s.whiteBalance || 4500;
        document.getElementById('wb-val').textContent = (s.whiteBalance || 4500) + 'K';

        toggleManualExposure(!s.autoExposure);
        toggleManualWb(!s.autoWhiteBalance);
    } catch (error) {
        console.error('Error loading settings:', error);
    }
}

// Apply settings to server
async function applySettings() {
    const statusEl = document.getElementById('settings-status');
    statusEl.textContent = 'Applying...';
    statusEl.className = 'settings-status';

    const settings = {
        resolution: document.getElementById('set-resolution').value,
        depthMode: document.getElementById('set-depth').value,
        compression: document.getElementById('set-compression').value,
        brightness: parseInt(document.getElementById('set-brightness').value),
        autoExposure: document.getElementById('set-auto-exposure').checked,
        exposure: parseInt(document.getElementById('set-exposure').value),
        gain: parseInt(document.getElementById('set-gain').value),
        autoWhiteBalance: document.getElementById('set-auto-wb').checked,
        whiteBalance: parseInt(document.getElementById('set-wb').value)
    };

    try {
        const response = await fetch('/api/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(settings)
        });
        const data = await response.json();

        if (data.success) {
            statusEl.textContent = 'Settings applied';
            statusEl.className = 'settings-status settings-ok';
            showNotification('Camera settings updated', 'success');
        } else {
            statusEl.textContent = 'Error: ' + data.message;
            statusEl.className = 'settings-status settings-err';
            showNotification(data.message, 'error');
        }
    } catch (error) {
        statusEl.textContent = 'Failed to apply';
        statusEl.className = 'settings-status settings-err';
        showNotification('Failed to apply settings', 'error');
    }

    setTimeout(function() { statusEl.textContent = ''; }, 4000);
}

// --- WebRTC Live View ---

async function checkWebrtcAvailable() {
    try {
        const response = await fetch('/api/webrtc/status');
        const data = await response.json();
        webrtcAvailable = data.available;
        const btn = document.getElementById('btn-live');
        if (!webrtcAvailable) {
            btn.disabled = true;
            btn.textContent = 'Live View Unavailable';
            document.getElementById('live-status').textContent = 'WebRTC not installed on server';
        }
    } catch (error) {
        console.error('Error checking WebRTC status:', error);
    }
}

async function toggleLiveView() {
    if (peerConnection) {
        stopLiveView();
    } else {
        await startLiveView();
    }
}

async function startLiveView() {
    if (!webrtcAvailable) return;

    const btn = document.getElementById('btn-live');
    const video = document.getElementById('live-video');
    const overlay = document.getElementById('live-overlay');
    const statusEl = document.getElementById('live-status');

    btn.textContent = 'Connecting...';
    btn.disabled = true;
    statusEl.textContent = '';

    try {
        peerConnection = new RTCPeerConnection({
            iceServers: [{urls: 'stun:stun.l.google.com:19302'}]
        });

        peerConnection.addEventListener('track', function(event) {
            video.srcObject = event.streams[0];
            overlay.style.display = 'none';
        });

        peerConnection.addEventListener('connectionstatechange', function() {
            const state = peerConnection.connectionState;
            if (state === 'connected') {
                btn.textContent = 'Stop Live View';
                btn.disabled = false;
                btn.classList.add('btn-active');
                statusEl.textContent = 'Streaming';
                statusEl.className = 'live-status live-connected';
            } else if (state === 'disconnected' || state === 'failed' || state === 'closed') {
                stopLiveView();
            }
        });

        // Request video only
        peerConnection.addTransceiver('video', { direction: 'recvonly' });

        const offer = await peerConnection.createOffer();
        await peerConnection.setLocalDescription(offer);

        // Wait for ICE gathering to complete
        await new Promise(function(resolve) {
            if (peerConnection.iceGatheringState === 'complete') {
                resolve();
            } else {
                peerConnection.addEventListener('icegatheringstatechange', function() {
                    if (peerConnection.iceGatheringState === 'complete') {
                        resolve();
                    }
                });
            }
        });

        // Send offer to server
        const response = await fetch('/api/webrtc/offer', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                sdp: peerConnection.localDescription.sdp,
                type: peerConnection.localDescription.type
            })
        });

        if (!response.ok) {
            throw new Error('Server returned ' + response.status);
        }

        const answer = await response.json();
        await peerConnection.setRemoteDescription(new RTCSessionDescription(answer));

    } catch (error) {
        console.error('WebRTC error:', error);
        showNotification('Failed to start live view: ' + error.message, 'error');
        stopLiveView();
    }
}

function stopLiveView() {
    if (peerConnection) {
        peerConnection.close();
        peerConnection = null;
    }

    const video = document.getElementById('live-video');
    const overlay = document.getElementById('live-overlay');
    const btn = document.getElementById('btn-live');
    const statusEl = document.getElementById('live-status');

    video.srcObject = null;
    overlay.style.display = 'flex';
    btn.textContent = 'Start Live View';
    btn.disabled = !webrtcAvailable;
    btn.classList.remove('btn-active');
    statusEl.textContent = '';
    statusEl.className = 'live-status';
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
    initWebSocket();
    initSettingsListeners();
    loadSettings();
    checkWebrtcAvailable();
    
    // Refresh status periodically as backup
    setInterval(async function() {
        try {
            const response = await fetch('/api/status');
            const status = await response.json();
            updateStatusDisplay(status);
        } catch (error) {
            console.error('Error fetching status:', error);
        }
    }, 5000);
});
