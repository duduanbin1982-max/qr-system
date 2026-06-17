// ═══════════════════════════════════════════
//  登录 / 主页面 / 闪光灯
// ═══════════════════════════════════════════

var _loginBusy = false;
function doLogin() {
  const u = $('inp-user').value.trim(), p = $('inp-pwd').value;
  if (_loginBusy) return;
  if (!u || !p) { toast('请输入用户名和密码'); return; }
  const btn = $('btn-login');
  btn.disabled = true; btn.innerHTML = '<span class=\"spin\"></span>登录中...';
  fetch(API + '/auth/login', {
    credentials: 'same-origin',
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: u, password: p })
  })
  .then(function(r) { return r.json(); })
  .then(function(d) {
    btn.disabled = false; btn.textContent = '登 录'; _loginBusy = false;
    if (d.error) { $('login-err').textContent = d.error; return; }
    window.__qr_user = d.user;
    try { sessionStorage.setItem('qr_user', JSON.stringify(d.user)); } catch(e) {}
    if (d.must_change_password) {
      showChangePassword();
      return;
    }
    goMain();
  })
  .catch(function() { $('login-err').textContent = '网络错误'; btn.disabled = false; btn.textContent = '登 录'; _loginBusy = false; });
}

function doLogout() {
  fetch(API + '/auth/logout', {
    credentials: 'same-origin',
    method: 'POST',
    headers: { 'Authorization': 'Bearer ' + token() }
  }).catch(function() {});
  window.__qr_user = null;
  try { sessionStorage.clear(); } catch(e) {}
  show('login');
}
function goMain() {
  $('inp-code').value = '';
  curOrder = null; curProcId = null; curSerial = '';
  reportMode = 'auto'; reportType = 'normal';
  switchMode('auto');
  setReportType('normal');
  var u = user();
  $('top-user').textContent = (u ? (u.name || u.username) : '扫码报工');
  $('manual-row').style.display = 'none';
  show('main');
  loadStats();
  loadRecent();
}

function goBack() { curOrder = null; show('main'); loadStats(); loadRecent(); }

function toggleManual() {
  var row = $('manual-row');
  row.style.display = row.style.display === 'flex' ? 'none' : 'flex';
  if (row.style.display === 'flex') setTimeout(function(){ $('inp-code').focus(); }, 100);
}

function loadStats() {
  fetch(API + '/personal/stats', { credentials: 'same-origin', headers: { 'Authorization': 'Bearer ' + token() } })
    .then(function(r) { return r.json(); })
    .then(function(d) {
      if (d && d.today) {
        $('st-today').textContent = d.today.records || 0;
        $('st-qty').textContent = d.today.quantity || 0;
      }
    })
    .catch(function() { });
}

function loadRecent() {
  fetch(API + '/personal/stats', { credentials: 'same-origin', headers: { 'Authorization': 'Bearer ' + token() } })
    .then(function(r) { return r.json(); })
    .then(function(d) {
      const list = d.recent_records || [];
      const el = $('recent-list');
      if (!list.length) { el.innerHTML = '<div class="empty-recent"><span class="icon">📋</span>暂无记录</div>'; return; }
      el.innerHTML = list.slice(0, 5).map(function(r) {
        const cls = r.type === 'scrap' ? 'scrap' : r.type === 'rework' ? 'rework' : 'normal';
        const lbl = r.type === 'scrap' ? '报废' : r.type === 'rework' ? '返修' : '正常';
        const time = (r.created_at || '').replace('T', ' ').substring(5, 16);
        return '<div class="recent-item">' +
          '<div class="ri-left"><div class="ri-no">' + esc(r.order_no || '') + ' · ' + esc(r.process_name || '') + '</div>' +
          '<div class="ri-meta">' + time + ' · ' + (r.quantity || 0) + '件</div></div>' +
          '<span class="ri-type ' + cls + '">' + lbl + '</span></div>';
      }).join('');
    })
    .catch(function() { });
}

function manualSearch() {
  const c = $('inp-code').value.trim();
  if (!c) { toast('请输入订单号或序列号'); return; }
  processCode(c);
}

function toggleFlash() {
  if (!camStream) return;
  const track = camStream.getVideoTracks()[0];
  if (!track || typeof track.applyConstraints !== 'function') {
    toast('此设备不支持闪光灯');
    return;
  }
  flashOn = !flashOn;
  track.applyConstraints({ advanced: [{ torch: flashOn }] })
    .then(function() { $('flash-btn').classList.toggle('off', !flashOn); })
    .catch(function() { toast('闪光灯不可用'); });
}

// ── 修改密码 ──────────────────────────────
function showChangePassword() {
  show('change-pwd');
}
function doChangePassword() {
  var oldPw = $('cp-old').value;
  var newPw = $('cp-new').value;
  var newPw2 = $('cp-new2').value;
  var errEl = $('cp-err');
  if (!oldPw) { errEl.textContent = '请输入原密码'; return; }
  if (!newPw || newPw.length < 6) { errEl.textContent = '新密码至少6位'; return; }
  if (newPw !== newPw2) { errEl.textContent = '两次密码不一致'; return; }
  var btn = $('btn-cp');
  btn.disabled = true; btn.textContent = '修改中...';
  fetch(API + '/auth/change-password', {
    credentials: 'same-origin',
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token() },
    body: JSON.stringify({ old_password: oldPw, new_password: newPw })
  })
  .then(function(r) { return r.json(); })
  .then(function(d) {
    btn.disabled = false; btn.textContent = '确认修改';
    if (d.error) { errEl.textContent = d.error; return; }
    goMain();
  })
  .catch(function() { errEl.textContent = '网络错误'; btn.disabled = false; btn.textContent = '确认修改'; });
}
