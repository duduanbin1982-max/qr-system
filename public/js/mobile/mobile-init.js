// ═══════════════════════════════════════════
//  初始化
// ═══════════════════════════════════════════
(function() {
  // Restore session if user was previously logged in (sessionStorage + valid cookie)
  if (user()) {
    // Verify cookie is still valid with a lightweight API call
    fetch(API + '/auth/info', { credentials: 'same-origin' })
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
  
  _el = document.querySelector('.recent-title span[style*="cursor:pointer"]');
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
  $('inp-pwd').addEventListener('keyup', function(e) { if (e.key === 'Enter') doLogin(); });
  $('inp-user').addEventListener('keyup', function(e) { if (e.key === 'Enter') $('inp-pwd').focus(); });
  $('inp-code').addEventListener('keyup', function(e) { if (e.key === 'Enter') manualSearch(); });
  window.addEventListener('beforeunload', function() {
    if (scanTimer) { clearInterval(scanTimer); scanTimer = null; }
    if (camStream) { camStream.getTracks().forEach(function(t) { t.stop(); }); camStream = null; }
  });
  // Responsive viewport height (Honor/Huawei virtual nav bar fix)
  function setVH() { document.documentElement.style.setProperty('--vh', (window.innerHeight * 0.01) + 'px'); }
  window.addEventListener('resize', setVH);
  window.addEventListener('orientationchange', function() { setTimeout(setVH, 100); });
  setVH();
})();