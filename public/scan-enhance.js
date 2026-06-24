// Flashlight toggle
function toggleFlash() {
  if (!camStream) { toast('No camera stream'); return; }
  var tracks = camStream.getVideoTracks();
  if (tracks.length === 0) { toast('No video track'); return; }
  var track = tracks[0];
  var caps = track.getCapabilities ? track.getCapabilities() : null;
  if (!caps || !caps.torch) { toast('Flash not supported on this device'); return; }
  var btn = document.getElementById('flash-btn');
  if (track.getSettings().torch) {
    track.applyConstraints({ advanced: [{torch: false}] });
    if (btn) { btn.className = 'flash-btn off'; btn.textContent = '\u26a1'; }
  } else {
    track.applyConstraints({ advanced: [{torch: true}] });
    if (btn) { btn.className = 'flash-btn on'; btn.textContent = '\u2600\ufe0f'; }
  }
}

// Close camera and return to main
function closeCam() {
  if (camStream) {
    camStream.getTracks().forEach(function(t) { t.stop(); });
    camStream = null;
  }
  var video = document.getElementById('cam-video');
  if (video) video.srcObject = null;
  show('main');
}

// Continuous scan mode
var continuousMode = false;
var scanCount = 0;

function toggleContinuous() {
  continuousMode = !continuousMode;
  var btn = document.getElementById('continuous-btn');
  if (btn) {
    if (continuousMode) {
      btn.className = 'continuous-btn on';
      btn.textContent = 'ON';
      toast('Continuous scan: ON');
    } else {
      btn.className = 'continuous-btn off';
      btn.textContent = 'OFF';
    }
  }
}
