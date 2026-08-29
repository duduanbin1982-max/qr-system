'use strict';
// ═══════════════════════════════════════════
//  登录 / 主页面 / 闪光灯
// ═══════════════════════════════════════════

var _loginBusy = false;
var _logoutBusy = false;

function persistMobileUser(serverUser) {
  var previous = user() || {};
  var merged = Object.assign({}, previous, serverUser || {});
  delete merged.token;
  window.__qr_user = merged;
  var safe = {
    id: merged.id,
    name: merged.name,
    username: merged.username,
    role: merged.role,
    permissions: merged.permissions || [],
    position_id: merged.position_id || null,
    position_name: merged.position_name || '',
    active_position_id: merged.active_position_id || null,
    active_position_name: merged.active_position_name || '',
    available_positions: merged.available_positions || []
  };
  try {
    sessionStorage.setItem('qr_user', JSON.stringify(safe));
    sessionStorage.removeItem('iq_token');
  } catch(e) {}
  return merged;
}

function clearMobileSessionState() {
  window.__qr_user = null;
  try {
    sessionStorage.removeItem('qr_user');
    sessionStorage.removeItem('iq_token');
    sessionStorage.removeItem('iq_code');
  } catch(e) {}
}

window.handleAuthExpired = function() {
  if (typeof releaseCamResources === 'function') releaseCamResources();
  clearMobileSessionState();
  show('login');
};

function applyPositionContext(context) {
  if (!context) return;
  var primary = context.primary_position || {};
  var active = context.active_position || {};
  persistMobileUser({
    position_id: primary.id || (user() && user().position_id) || null,
    position_name: primary.name || '',
    active_position_id: context.active_position_id || null,
    active_position_name: active.name || '',
    available_positions: context.available_positions || []
  });
  renderActivePosition();
}

function renderActivePosition() {
  var container = $('position-context');
  var select = $('active-position-select');
  var hint = $('active-position-hint');
  if (!container || !select || !hint) return;
  var currentUser = user();
  var positions = currentUser && currentUser.available_positions || [];
  container.hidden = false;
  select.innerHTML = '';
  if (!positions.length) {
    var emptyOption = document.createElement('option');
    emptyOption.value = '';
    emptyOption.textContent = '未配置岗位';
    select.appendChild(emptyOption);
    select.disabled = true;
    hint.textContent = '将按个人工序授权判定';
    return;
  }
  positions.forEach(function(position) {
    var option = document.createElement('option');
    option.value = String(position.id);
    option.textContent = position.name + (position.is_primary ? '（主岗位）' : '');
    option.selected = String(position.id) === String(currentUser.active_position_id);
    select.appendChild(option);
  });
  select.disabled = positions.length < 2;
  var active = positions.find(function(position) {
    return String(position.id) === String(currentUser.active_position_id);
  }) || positions[0];
  hint.textContent = active.process_ids && active.process_ids.length
    ? '关联 ' + active.process_ids.length + ' 道工序'
    : '暂无关联工序';
}

function changeActivePosition() {
  var select = $('active-position-select');
  if (!select || !select.value) return;
  var previousId = user() && user().active_position_id;
  if (String(select.value) === String(previousId)) return;
  select.disabled = true;
  api.setActivePosition({ position_id: parseInt(select.value, 10) })
    .then(function(context) {
      applyPositionContext(context);
      toast('当前岗位已切换为' + ((context.active_position || {}).name || '所选岗位'));
    })
    .catch(function(error) {
      renderActivePosition();
      toast((error && error.message) || '岗位切换失败');
    });
}

function doLogin() {
  const u = $('inp-user').value.trim(), p = $('inp-pwd').value;
  if (_loginBusy) return;
  if (!u || !p) { toast('请输入用户名和密码'); return; }
  const btn = $('btn-login');
  _loginBusy = true;
  btn.disabled = true; btn.innerHTML = '<span class=\"spin\"></span>登录中...';
  api.login({ username: u, password: p })
  .then(function(d) {
    btn.disabled = false; btn.textContent = '登 录'; _loginBusy = false;
    if (d.error) { $('login-err').textContent = d.error; return; }
    persistMobileUser(d.user);
    if (d.must_change_password) {
      showChangePassword();
      return;
    }
    goMain();
  })
  .catch(function(e) { $('login-err').textContent = (e && e.message) || '网络错误'; btn.disabled = false; btn.textContent = '登 录'; _loginBusy = false; });
}

function doLogout() {
  if (_logoutBusy) return;
  _logoutBusy = true;
  if (typeof releaseCamResources === 'function') releaseCamResources();
  if (typeof releasePhotoResources === 'function') releasePhotoResources();
  var link = document.querySelector('.bottom-link');
  if (link) {
    link.setAttribute('aria-busy', 'true');
    link.textContent = '退出中...';
  }
  var settled = api.logout()
    .then(function() { return { ok: true }; })
    .catch(function(error) { return { ok: false, error: error }; });
  var timeoutId;
  var timeout = new Promise(function(resolve) {
    timeoutId = setTimeout(function() { resolve({ ok: false, timeout: true }); }, 5000);
  });
  Promise.race([settled, timeout]).then(function(result) {
    clearTimeout(timeoutId);
    clearMobileSessionState();
    _logoutBusy = false;
    if (link) {
      link.removeAttribute('aria-busy');
      link.textContent = '退出登录';
    }
    show('login');
    if (!result.ok) {
      toast(result.timeout
        ? '服务端注销超时，本地已退出，请稍后重试'
        : '服务端注销未确认，本地已退出，请检查网络');
    }
  });
}
function goMain() {
  if (typeof releaseCamResources === 'function') releaseCamResources();
  if (typeof releasePhotoResources === 'function') releasePhotoResources();
  $('inp-code').value = '';
  curOrder = null; curProcId = null; curSerial = '';
  reportMode = 'auto'; reportType = 'normal';
  switchMode('auto');
  setReportType('normal');
  var u = user();
  $('top-user').textContent = (u ? (u.name || u.username) : '扫码报工');
  renderActivePosition();
  $('manual-row').style.display = 'none';
  show('main');
  loadStats();
  loadRecent();
  loadQualityEvaluationCount();
}

function goBack() {
  if (typeof releaseCamResources === 'function') releaseCamResources();
  if (typeof releasePhotoResources === 'function') releasePhotoResources();
  curOrder = null; reportMode = 'auto'; reportType = 'normal'; show('main'); loadStats(); loadRecent();
}

function toggleManual() {
  var row = $('manual-row');
  row.style.display = row.style.display === 'flex' ? 'none' : 'flex';
  if (row.style.display === 'flex') setTimeout(function(){ $('inp-code').focus(); }, 100);
}

function loadStats() {
  api.personalStats()
    .then(function(d) {
      if (!d) return;
      if (d && d.today) {
        $('st-today').textContent = d.today.records || 0;
        $('st-qty').textContent = d.today.quantity || 0;
      }
    })
    .catch(function() { });
}

function loadRecent() {
  api.personalStats()
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
  api.changePassword({ old_password: oldPw, new_password: newPw })
  .then(function(d) {
    btn.disabled = false; btn.textContent = '确认修改';
    if (d.error) { errEl.textContent = d.error; return; }
    goMain();
  })
  .catch(function(e) { errEl.textContent = (e && e.message) || '网络错误'; btn.disabled = false; btn.textContent = '确认修改'; });
}
