// ═══════════════════════════════════════════
//  二维码内容处理模块
// ═══════════════════════════════════════════

function processCode(code) {
  // 数字编码(N前缀) → 通过 decode API 还原为 JSON
  if (/^N\d{10,}$/.test(code)) {
    toast('解码中...');
    fetch(API + '/mobile/decode/' + code, {
      credentials: 'same-origin',
      headers: { 'Authorization': 'Bearer ' + token() }
    })
    .then(function(r) { return r.json(); })
    .then(function(d) {
      if (d.error) { toast(d.error); show('main'); return; }
      doScan(d.code);
    })
    .catch(function() { toast('二维码数据解码失败，请确认二维码有效'); show('main'); });
    return;
  }
  doScan(code);
}

function doScan(code) {
  toast('查询中...');
  fetch(API + '/mobile/scan', {
    credentials: 'same-origin',
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token() },
    body: JSON.stringify({ code: code })
  })
  .then(function(r) { return r.json(); })
  .then(function(d) {
    if (d.error) { toast(d.error); show('main'); return; }
    if (d.item) { d.order.item = d.item; }

    // -- 管理员/质检员扫码 → 重定向到抽检页面 --
    var _u = user();
    if (_u && _u.permissions && (_u.permissions.indexOf("*") !== -1 || _u.permissions.indexOf("inspection:create") !== -1 || _u.permissions.indexOf("quality:view") !== -1)) {
      closeCam();
      window.location.href = "/mobile_inspection.html?code=" + encodeURIComponent(code) + "&token=" + encodeURIComponent(token());
      return;
    }

    renderOrder(d.order);
    show('order');
    // 序列号模式：每张二维码对应1件工件，数量恒为1
    // 订单模式：取工序剩余待完成数
    // 序列号模式：每张二维码对应1件，数量锁定为1，禁止修改
    var isSerialMode = !!(curSerial || d.item || d.order.has_items);
    var remaining = isSerialMode ? 1
      : Math.max(0, d.order.current_process
        ? (d.order.quantity || 0) - (d.order.current_process.completed || 0)
        : 1);
    $("rpt-qty").value = remaining;
    if (isSerialMode) {
      $("rpt-qty").disabled = true;
      $("rpt-qty").title = "序列号模式，数量固定为1";
    } else {
      $("rpt-qty").disabled = false;
      $("rpt-qty").title = "";
    }
    if (reportMode === 'auto') {
      setTimeout(function() { doReport(); }, 1200);
    } else {
      updateReportBtn();
    }
  })
  .catch(function(e) { console.log('scan auth fail — token:' + (token() ? 'yes' : 'no') + ' cookie:' + (document.cookie.indexOf('qr_token')>=0 ? 'yes' : 'no')); toast('网络异常'); show('main'); });
}

// ═══════════════════════════════════════════
//  订单展示 & 报工
// ═══════════════════════════════════════════

function renderOrder(o) {
  curOrder = o; curProcId = null; curSerial = '';
  var b = $('order-body'), cp = o.current_process, qty = o.quantity || 0;
  var h = '';

  h += '<div class="order-header"><div class="no">' + esc(o.order_no || '') + '</div>';
  h += '<div class="row"><span>产品</span><span>' + esc(o.product_name || '') + '</span></div>';
  h += '<div class="row"><span>客户</span><span>' + esc(o.customer || '') + '</span></div>';
  h += '<div class="row"><span>数量</span><span>' + qty + ' 件</span></div></div>';

  if (o.item) {
    curSerial = o.item.serial_no;
    h += '<div class="serial-card"><div class="label">序列号</div><div class="val">' + esc(o.item.serial_no) + '</div></div>';
  }

  if (cp) {
    var dn = cp.completed || 0, rm = Math.max(0, qty - dn);
    curProcId = cp.process_id;
    h += '<div class="cur-proc"><span class="badge">当前工序</span>';
    h += '<div class="name">' + esc(cp.process_name || '') + '</div>';
    h += '<div class="sub">已完成 ' + dn + '/' + qty + ' · 剩余 ' + rm + ' 件</div></div>';
  }

  h += '<div class="proc-card"><div class="title">工艺路线（' + (o.processes || []).length + ' 个工序）</div>';
  (o.processes || []).forEach(function(p) {
    var d = p.completed || 0;
    var s = 'pending';
    if (d >= qty) s = 'done';
    else if (p.process_id === (cp && cp.process_id)) s = 'active';
    h += '<div class="proc-item ' + s + '"><div class="pi-icon">' + (p.seq_order || '') + '</div>';
    h += '<div class="pi-info"><div class="pi-name">' + esc(p.process_name) + '</div>';
    h += '<div class="pi-meta">已完成 ' + d + '/' + qty + '</div></div>';
    h += '<div class="pi-st">' + (s === 'done' ? '已完成' : s === 'active' ? '进行中' : '待处理') + '</div></div>';
  });
  h += '</div>';
  b.innerHTML = h;
}

// ── 报工模式 ─────────────────────────────────
function switchMode(mode) {
  reportMode = mode;
  $('mode-auto').classList.toggle('active', mode === 'auto');
  $('mode-manual').classList.toggle('active', mode === 'manual');
  $('report-form').style.display = (mode === 'manual' ? 'block' : 'none');
  updateReportBtn();
}

function setReportType(type) {
  reportType = type;
  ['normal','scrap','rework'].forEach(function(t) {
    $('rtype-' + t).classList.toggle('active', t === type);
  });
  $('reason-row').style.display = (type === 'normal') ? 'none' : 'block';
  updateReportBtn();
}

function updateReportBtn() {
  const btn = $('btn-report');
  var qty = parseInt($('rpt-qty').value) || 0;
  if (qty <= 0) { btn.disabled = true; btn.textContent = '已完成全部报工'; return; }
  const label = reportType === 'normal' ? '正常' : reportType === 'scrap' ? '报废' : '返修';
  if (reportMode === 'auto') {
    btn.textContent = '⚡ 自动报工 ' + qty + ' 件 (' + label + ')';
    btn.disabled = false;
  } else {
    btn.textContent = '✋ 提交报工 ' + qty + ' 件 (' + label + ')';
    btn.disabled = !curOrder || !curProcId;
  }
  btn.className = 'btn-report' + (reportType !== 'normal' ? ' ' + reportType : '');
}

$('rpt-qty').addEventListener('input', updateReportBtn);

// ── 提交报工 ─────────────────────────────────
function doReport() {
  if (!curOrder || !curProcId) { toast('订单信息不完整'); return; }
  const btn = $('btn-report');
  btn.disabled = true; btn.innerHTML = '<span class=\"spin\"></span>提交中...';

  var body = {
    order_id: curOrder.id,
    process_id: curProcId,
    quantity: parseInt($('rpt-qty').value) || 1,
    report_type: reportType
  };
  if (reportType !== 'normal') {
    body.remark = ($('rpt-reason').value || '').trim() || '未填写';
  }
  if (curSerial) body.serial_no = curSerial;

  fetch(API + '/mobile/report', {
    credentials: 'same-origin',
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token() },
    body: JSON.stringify(body)
  })
  .then(function(r) { return r.json(); })
  .then(function(d) {
    if (d.error) { toast(d.error); btn.disabled = false; updateReportBtn(); return; }
    const qty = body.quantity || 1;
    const label = reportType === 'normal' ? '正常报工' : reportType === 'scrap' ? '报废' : '返修';
    $('ok-msg').textContent = (curOrder.order_no || '') + ' · ' + (curOrder.current_process && curOrder.current_process.process_name || '');
    $('ok-detail').innerHTML =
      '<div>📦 订单: ' + esc(curOrder.order_no || '') + '</div>' +
      '<div>⚙️ 工序: ' + esc(curOrder.current_process && curOrder.current_process.process_name || '') + '</div>' +
      '<div>📊 数量: ' + qty + ' 件</div>' +
      '<div>🏷️ 类型: ' + label + '</div>' +
      '<div>👤 操作人: ' + esc(d.worker ? d.worker.name : (user() ? user().name : '未知')) + '</div>';
    show('ok');
  })
  .catch(function() { toast('网络异常'); btn.disabled = false; updateReportBtn(); });
}