// ═══════════════════════════════════════════
//  双引擎扫码模块
// ═══════════════════════════════════════════

// ── 打开摄像头 ──────────────────────────────
function openCam() {
  show('scan');

  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    toast('无摄像头权限');
    show('main');
    return;
  }

  $('scan-engine').textContent = '引擎: jsQR (通用软件解码)';

  const video = $('cam-video');
  navigator.mediaDevices.getUserMedia({
    video: { facingMode: 'environment', width: { ideal: 1280 }, height: { ideal: 720 } }
  })
  .then(function(stream) {
    camStream = stream;
    video.srcObject = stream;
    video.play().then(function() {
      startJsQR(video);
    });
  })
  .catch(function(err) {
    var msg;
    if (err.name === 'NotAllowedError')
      msg = '摄像头权限被拒绝。请在浏览器设置中允许摄像头，或使用拍照解码';
    else if (err.name === 'NotFoundError')
      msg = '未检测到摄像头设备';
    else if (err.name === 'NotReadableError')
      msg = '摄像头被其他应用占用';
    else
      msg = '摄像头错误: ' + (err.message || err.name || '未知');
    toast(msg, 5000);
    show('main');
  });
}

// ── 路径2: jsQR (纯JS通用降级) ─────────────
// 对齐 .74 scan.html：原始分辨率全图，一次jsQR
function startJsQR(video) {
  const canvas = $('cam-canvas');
  const ctx = canvas.getContext('2d');

  scanTimer = setInterval(function() {
    if (!camStream) return;
    if (video.readyState !== video.HAVE_ENOUGH_DATA) return;

    canvas.width  = video.videoWidth;
    canvas.height = video.videoHeight;
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

    const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
    const code = jsQR(imageData.data, imageData.width, imageData.height);
    
    if (code && code.data) {
      const now = Date.now();
      if (code.data === lastCode && now - lastTime < 3000) return;
      lastCode = code.data; lastTime = now;
      onScan(code.data);
    }
  }, 300);
}


// ── 停止扫描（保留摄像头画面）───────────────
function stopScanner() {
  if (scanTimer) { clearInterval(scanTimer); scanTimer = null; }
}
function onScan(text) {
  stopScanner();
  var f = document.createElement('div'); f.className = 'scan-flash';
  document.body.appendChild(f);
  setTimeout(function(){ f.style.opacity='0'; setTimeout(function(){ f.remove(); },400); },50);
  setTimeout(function() { processCode(text); }, 200);
}

// ── 关闭摄像头 ───────────────────────────────
function closeCam() {
  if (scanTimer) { clearInterval(scanTimer); scanTimer = null; }
  if (camStream) {
    camStream.getTracks().forEach(function(t) { t.stop(); });
    camStream = null;
  }
  const v = $('cam-video');
  if (v) v.srcObject = null;
  flashOn = false;
  $('flash-btn').classList.add('off');
  $('scan-engine').textContent = '';
  show('main');
}

// ═══════════════════════════════════════════
//  拍照解码模块
// ═══════════════════════════════════════════

function openPhoto() {
  $('photo-input').click();
}

function handlePhoto(e) {
  const file = e.target.files[0];
  if (!file) return;
  toast('解码中...');

  const img = new Image();
  img.onload = function() {
    // 限制最大分辨率以加速解码
    const maxW = 1200;
    let w = img.width, h = img.height;
    if (w > maxW) { h = Math.round(h * maxW / w); w = maxW; }

    var canvas = document.createElement('canvas');
    canvas.width  = w;
    canvas.height = h;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(img, 0, 0, w, h);

    try {
      var imgData = ctx.getImageData(0, 0, w, h);
      const result = jsQR(imgData.data, w, h);
      if (result && result.data) {
        processCode(result.data);
      } else {
        // 全图失败 → 尝试中心裁剪
        const cx = Math.round(w * 0.25);
        const cy = Math.round(h * 0.25);
        const cw2 = Math.round(w * 0.5);
        const ch2 = Math.round(h * 0.5);
        const cropData = ctx.getImageData(cx, cy, cw2, ch2);
        const result2 = jsQR(cropData.data, cw2, ch2);
        if (result2 && result2.data) {
          processCode(result2.data);
        } else {
          toast('未识别到二维码');
          show('main');
        }
      }
    } catch(err) {
      toast('解码异常: ' + (err.message || '图片处理失败'));
      show('main');
    }
  };
  img.onerror = function() {
    toast('图片加载失败，请重试');
    show('main');
  };
  img.src = URL.createObjectURL(file);
  img.addEventListener('load', function() { URL.revokeObjectURL(img.src); });
  img.addEventListener('error', function() { URL.revokeObjectURL(img.src); });
  e.target.value = '';
}