'use strict';
// ═══════════════════════════════════════════
//  初始化
// ═══════════════════════════════════════════
(function() {
  // Restore session if user was previously logged in (sessionStorage + valid cookie)
  if (user()) {
    // Verify cookie is still valid with a lightweight API call
    fetch(API + '/auth/info', { credentials: 'same-origin', headers: { 'Authorization': 'Bearer ' + token() } })
      .then(function(r) { return r.json(); })
      .then(function(d) {
        if (d && d.user) { goMain(); }
        else { doLogout(); }
      })
      .catch(function() { doLogout(); });
  } else {
    show('login');
  }

  // === Event listeners (migrated from inline handlers for CSP strict mode) ===
  var _el = document.getElementById('btn-login');
  if (_el) _el.addEventListener('click', doLogin);
  
  _el = document.querySelector('.hero-scan');
  if (_el) _el.addEventListener('click', openCam);
  
  var _subBtns = document.querySelectorAll('.sub-btn');
  if (_subBtns[0]) _subBtns[0].addEventListener('click', openPhoto);
  if (_subBtns[1]) _subBtns[1].addEventListener('click', toggleManual);
  
  _el = document.querySelector('#manual-row button');
  if (_el) _el.addEventListener('click', manualSearch);
  
  _el = document.getElementById('photo-input');
  if (_el) _el.addEventListener('change', handlePhoto);
  
  _el = document.querySelector('#manual-row input');
  if (_el) _el.addEventListener('keyup', function(e) { if (e.key === 'Enter') manualSearch(); });
  
  _el = document.querySelector('.recent-title .refresh-btn');
  if (_el) _el.addEventListener('click', loadRecent);
  
  _el = document.querySelector('.bottom-link');
  if (_el) _el.addEventListener('click', doLogout);
  
  _el = document.querySelector('.top-btn');
  if (_el) _el.addEventListener('click', goBack);
  
  _el = document.getElementById('mode-auto');
  if (_el) _el.addEventListener('click', function() { switchMode('auto'); });
  
  _el = document.getElementById('mode-manual');
  if (_el) _el.addEventListener('click', function() { switchMode('manual'); });
  
  _el = document.getElementById('rtype-normal');
  if (_el) _el.addEventListener('click', function() { setReportType('normal'); });
  
  _el = document.getElementById('rtype-scrap');
  if (_el) _el.addEventListener('click', function() { setReportType('scrap'); });
  
  _el = document.getElementById('rtype-rework');
  if (_el) _el.addEventListener('click', function() { setReportType('rework'); });
  
  _el = document.getElementById('btn-report');
  if (_el) _el.addEventListener('click', doReport);
  
  _el = document.querySelector('.btn-done');
  if (_el) _el.addEventListener('click', goMain);
  
  _el = document.getElementById('flash-btn');
  if (_el) _el.addEventListener('click', toggleFlash);
  
  _el = document.querySelector('.close-btn');
  if (_el) _el.addEventListener('click', closeCam);
  var _elPwd = $('inp-pwd'); if (_elPwd) _elPwd.addEventListener('keyup', function(e) { if (e.key === 'Enter') doLogin(); });
  var _elUser = $('inp-user'); if (_elUser) _elUser.addEventListener('keyup', function(e) { if (e.key === 'Enter') { var _pwd = $('inp-pwd'); if (_pwd) _pwd.focus(); } });
  var _elCode = $('inp-code'); if (_elCode) _elCode.addEventListener('keyup', function(e) { if (e.key === 'Enter') manualSearch(); });

  _el = document.getElementById('btn-cp');
  if (_el) _el.addEventListener('click', doChangePassword);
  
  _el = document.getElementById('cp-new2');
  if (_el) _el.addEventListener('keyup', function(e) { if (e.key === 'Enter') doChangePassword(); });

  window.addEventListener('beforeunload', function() {
    if (scanTimer) { clearInterval(scanTimer); scanTimer = null; }
    if (camStream) { camStream.getTracks().forEach(function(t) { t.stop(); }); camStream = null; }
  });
  // Responsive viewport height (Honor/Huawei virtual nav bar fix)
  function setVH() { document.documentElement.style.setProperty('--vh', (window.innerHeight * 0.01) + 'px'); }
  window.addEventListener('resize', setVH);
  window.addEventListener('orientationchange', function() { setTimeout(setVH, 100); });
  setVH();

  // C2: Service Worker registration (migrated from inline script)
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").then(function(reg) {
      console.log("SW registered:", reg.scope);
      reg.addEventListener("updatefound", function() {
        var worker = reg.installing;
        worker.addEventListener("statechange", function() {
          if (worker.state === "activated" && navigator.serviceWorker.controller) {
            var toast = document.createElement("div");
            toast.style.cssText = "position:fixed;top:0;left:0;right:0;background:#4F46E5;color:#fff;text-align:center;padding:8px;z-index:9999;cursor:pointer";
            toast.textContent = "有新版本，点击刷新";
            toast.addEventListener("click", function() { location.reload(); });
            document.body.appendChild(toast);
            setTimeout(function() { toast.remove(); }, 5000);
          }
        });
      });
    }).catch(function(e) { console.log("SW failed:", e); });

    window.addEventListener("online", function() {
      var bar = document.getElementById("offline-bar");
      if (bar) bar.remove();
    });
    window.addEventListener("offline", function() {
      var bar = document.createElement("div");
      bar.id = "offline-bar";
      bar.style.cssText = "position:fixed;top:0;left:0;right:0;background:#F59E0B;color:#fff;text-align:center;padding:6px;z-index:9999;font-size:14px";
      bar.textContent = "当前离线 - 数据将在恢复网络后同步";
      document.body.appendChild(bar);
    });
    if (!navigator.onLine) {
      window.dispatchEvent(new Event("offline"));
    }
  }
})();