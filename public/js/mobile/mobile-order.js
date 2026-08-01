// ═══════════════════════════════════════════
//  二维码内容处理模块
// ═══════════════════════════════════════════

function processCode(code) {
  // 数字编码(N前缀) → 通过 decode API 还原为 JSON
  if (/^N\d{10,}$/.test(code)) {
    toast('解码中...');
    api.decodeQR(code)
    .then(function(d) { doScan(d.code); })
    .catch(function(e) { toast((e && e.message) || '二维码数据解码失败，请确认二维码有效'); show('main'); });
    return;
  }
  doScan(code);
}

function doScan(code) {
  currentScanCode = code;
  toast('查询中...');
  api.mobileScan({ code: code })
  .then(function(d) {
    if (d.position_context) applyPositionContext(d.position_context);
    if (d.item) { d.order.item = d.item; }
    if (d.completion_focus_warning && d.order) {
      d.order.completion_focus_warning = d.completion_focus_warning;
    }

    // -- 管理员/质检员扫码 → 重定向到抽检页面 --
    var _u = user();
    if (_u && _u.permissions && (_u.permissions.indexOf("*") !== -1 || _u.permissions.indexOf("inspection:create") !== -1 || _u.permissions.indexOf("quality:inspect") !== -1 || _u.permissions.indexOf("quality:edit") !== -1)) {
      closeCam();
      try { sessionStorage.setItem("iq_token", token()); sessionStorage.setItem("iq_code", code); } catch(e) {}
      window.location.href = "/mobile_inspection.html?code=" + encodeURIComponent(code);
      return;
    }

    renderOrder(d.order);
    show('order');
    // 序列号模式：每张二维码对应1件工件，数量恒为1
    // 订单模式：取工序剩余待完成数
    // 序列号模式：每张二维码对应1件，数量锁定为1，禁止修改
    var isSerialMode = !!(curSerial || d.item || d.order.has_items);
    var selectedProcess = getSelectedReportProcess();
    var remaining = isSerialMode ? 1
      : Math.max(0, selectedProcess
        ? (selectedProcess.max_report_quantity || 0)
        : 0);
    $("rpt-qty").value = remaining;
    if (isSerialMode) {
      $("rpt-qty").disabled = true;
      $("rpt-qty").title = "序列号模式，数量固定为1";
    } else {
      $("rpt-qty").disabled = false;
      $("rpt-qty").title = "";
    }
    var backfillCandidates = getSerialBackfillCandidates();
    if (d.completion_focus_warning) {
      switchMode('manual');
      toast(d.completion_focus_warning.blocking ? '集中完工强拦截：请先处理前序订单' : '存在更早订单应优先收尾，已切换为手动确认', 3200);
      updateReportBtn();
    } else if (d.order.requires_process_selection) {
      switchMode('manual');
      toast(
        d.order.process_selection_source === 'position_manual'
          ? '当前岗位有多个可报工序，请确认本次工序'
          : (d.order.process_selection_message || '请选择本次报工工序'),
        3000
      );
      updateReportBtn();
    } else if (!canAutoReportSelectedProcess()) {
      switchMode('manual');
      toast(getUnavailableReportMessage(), 3200);
      updateReportBtn();
      if (backfillCandidates.length) focusFirstBackfillCandidate();
    } else if (reportMode === 'auto') {
      if (d.order.process_selection_source === 'position_auto') {
        toast('已按当前岗位自动匹配报工工序', 1800);
      } else if (d.order.process_selection_message) {
        toast(d.order.process_selection_message, 2600);
      }
      var autoOrderId = curOrder && curOrder.id;
      var autoProcessId = curProcId;
      setTimeout(function() {
        if (
          reportMode === 'auto' &&
          curOrder && String(curOrder.id) === String(autoOrderId) &&
          String(curProcId) === String(autoProcessId) &&
          canAutoReportSelectedProcess()
        ) {
          doReport();
        }
      }, 1200);
    } else {
      updateReportBtn();
    }
  })
  .catch(function(e) { console.log('scan failed — token:' + (token() ? 'yes' : 'no') + ' cookie:' + (document.cookie.indexOf('qr_token')>=0 ? 'yes' : 'no')); toast((e && e.message) || '网络异常'); show('main'); });
}

// ═══════════════════════════════════════════
//  订单展示 & 报工
// ═══════════════════════════════════════════

function renderOrder(o, requestedProcessId, requestedBackfillMode) {
  curOrder = o; curProcId = null; curSerial = '';
  serialBackfillMode = !!requestedBackfillMode;
  var b = $('order-body'), cp = o.current_process, qty = o.quantity || 0;
  var processes = o.processes || [];
  var selected = null;
  var h = '';

  h += '<div class="order-header"><div class="no">' + esc(o.order_no || '') + '</div>';
  h += '<div class="row"><span>产品</span><span>' + esc(o.product_name || '') + '</span></div>';
  h += '<div class="row"><span>客户</span><span>' + esc(o.customer || '') + '</span></div>';
  if (o.active_position) {
    h += '<div class="row"><span>当前岗位</span><span>' + esc(o.active_position.name || '') + '</span></div>';
  }
  var availablePositions = user() && user().available_positions || [];
  if (availablePositions.length > 1) {
    h += '<div class="order-position-row"><label for="order-active-position-select">本次岗位</label><select id="order-active-position-select">';
    availablePositions.forEach(function(position) {
      h += '<option value="' + esc(position.id) + '"' +
        (String(position.id) === String(user().active_position_id) ? ' selected' : '') + '>' +
        esc(position.name || '') + '</option>';
    });
    h += '</select></div>';
  }
  h += '<div class="row"><span>数量</span><span>' + qty + ' 件</span></div></div>';

  if (o.process_selection_message) {
    h += '<div class="position-match-notice">' + esc(o.process_selection_message) + '</div>';
  }

  if (o.completion_focus_warning && o.completion_focus_warning.message) {
    var isBlocked = !!o.completion_focus_warning.blocking;
    h += '<div class="focus-warning-card' + (isBlocked ? ' blocked' : '') + '">';
    h += '<div class="fw-title">🎯 ' + (isBlocked ? '集中完工强拦截' : '集中完工提示') + '</div>';
    h += '<div class="fw-msg">' + esc(o.completion_focus_warning.message) + '</div>';
    if (o.completion_focus_warning.recommended_order_no) {
      h += '<div class="fw-meta">建议优先订单：' + esc(o.completion_focus_warning.recommended_order_no) +
        ' · ' + esc(o.completion_focus_warning.recommended_process_name || '') +
        ' · 剩余 ' + (o.completion_focus_warning.recommended_backlog || 0) + ' 件</div>';
    }
    if (isBlocked) {
      h += '<div class="fw-meta">如确需插单，请联系管理员/生产主管在订单管理中设置例外订单。</div>';
    }
    h += '</div>';
  }

  if (o.item) {
    curSerial = o.item.serial_no;
    h += '<div class="serial-card"><div class="label">序列号</div><div class="val">' + esc(o.item.serial_no) + '</div></div>';
  }

  if (requestedProcessId) {
    selected = processes.find(function(p) {
      return String(p.process_id) === String(requestedProcessId) &&
        (serialBackfillMode ? p.serial_backfill_reportable : isNormalReportProcessSelectable(p));
    });
  }
  if (!selected && cp) {
    selected = processes.find(function(p) {
      return String(p.process_id) === String(cp.process_id) && isNormalReportProcessSelectable(p);
    });
  }
  if (!selected) {
    selected = processes.find(isNormalReportProcessSelectable);
    serialBackfillMode = false;
  }
  if (!selected && o.serial_backfill_selection_source === 'position_auto') {
    selected = processes.find(function(p) { return !!p.serial_backfill_reportable; });
    serialBackfillMode = !!selected;
  }

  var backfillCandidates = processes.filter(function(p) {
    return !!p.serial_backfill_reportable;
  });

  if (!selected && backfillCandidates.length) {
    h += '<div class="process-guidance" role="status">' + esc(getUnavailableReportMessage(o)) + '</div>';
  }

  if (selected) {
    var dn = selected.completed || 0;
    var rm = serialBackfillMode ? 1 : (selected.max_report_quantity || 0);
    curProcId = selected.process_id;
    h += '<div class="cur-proc' + (serialBackfillMode ? ' backfill' : '') + '"><span class="badge">' +
      (serialBackfillMode ? '跨工序补报' : '报工工序') + '</span>';
    h += '<div class="name">' + esc(selected.process_name || '') + '</div>';
    h += '<div class="sub">已完成 ' + dn + '/' + qty + ' · 本次最多 ' + rm + ' 件</div></div>';
  }

  h += '<div class="proc-card"><div class="title">选择报工工序（共 ' + processes.length + ' 道）</div>';
  processes.forEach(function(p, index) {
    var d = p.completed || 0;
    var s = 'pending';
    var selectable = isReportProcessSelectable(p);
    var serialState = p.serial_report_status || '';
    if (serialState === 'approved') s = 'done';
    else if (serialState === 'pending') s = 'pending approval-pending';
    else if (!curSerial && d >= qty) s = 'done';
    else if (String(p.process_id) === String(curProcId)) {
      s = serialBackfillMode ? 'active selected backfill-selectable' : 'active selected';
    }
    else if (p.serial_backfill_reportable) s = 'pending selectable backfill-selectable';
    else if (selectable) s = 'pending selectable';
    else s = 'pending blocked';
    var reportState = s.indexOf('selected') >= 0 ? '已选择'
      : serialState === 'approved' ? '已报工'
      : serialState === 'pending' ? '待审批'
      : p.serial_backfill_reportable ? '可补报'
      : selectable ? '可报工'
      : p.normal_reportable ? '其他岗位'
      : p.process_authorized === false ? '无权限' : '待前序';
    var actionable = selectable && s !== 'done' && serialState !== 'pending' && s.indexOf('selected') < 0;
    var actionLabel = actionable ? '选择工序' + (p.process_name || '') + '，' + reportState : '';
    h += '<button type="button" class="proc-item ' + s + '" data-process-id="' + (p.process_id || '') + '"' +
      (p.serial_backfill_reportable && actionable ? ' data-backfill-candidate="true"' : '') +
      (actionable ? ' aria-label="' + esc(actionLabel) + '"' : ' disabled') + '><div class="pi-icon">' + (index + 1) + '</div>';
    h += '<div class="pi-info"><div class="pi-name">' + esc(p.process_name) + '</div>';
    h += '<div class="pi-meta">订单进度：已完成 ' + d + '/' + qty + '</div></div>';
    h += '<div class="pi-st">' + (s === 'done' ? (curSerial ? '已报工' : '已完成') : reportState) + '</div></button>';
  });
  h += '</div>';
  b.innerHTML = h;
  var positionSelect = b.querySelector('#order-active-position-select');
  if (positionSelect) {
    positionSelect.addEventListener('change', function() {
      changeOrderActivePosition(positionSelect);
    });
  }
  Array.prototype.forEach.call(b.querySelectorAll('.proc-item.selectable'), function(element) {
    element.addEventListener('click', function() {
      selectReportProcess(element.getAttribute('data-process-id'));
    });
  });
  updateBackfillFields();
}

function changeOrderActivePosition(select) {
  if (!select || !select.value) return;
  var previousId = user() && user().active_position_id;
  if (String(select.value) === String(previousId)) return;
  select.disabled = true;
  api.setActivePosition({ position_id: parseInt(select.value, 10) })
    .then(function(context) {
      applyPositionContext(context);
      doScan(currentScanCode);
    })
    .catch(function(error) {
      select.disabled = false;
      toast((error && error.message) || '岗位切换失败');
    });
}

function isNormalReportProcessSelectable(process) {
  return !!(
    process && process.normal_reportable && process.position_reportable !== false
  );
}

function isReportProcessSelectable(process) {
  return !!(
    isNormalReportProcessSelectable(process) ||
    (process && process.serial_backfill_reportable)
  );
}

function getSelectedReportProcess() {
  if (!curOrder || !curProcId) return null;
  return (curOrder.processes || []).find(function(process) {
    return String(process.process_id) === String(curProcId);
  }) || null;
}

function getSerialBackfillCandidates() {
  return (curOrder && curOrder.processes || []).filter(function(process) {
    return !!process.serial_backfill_reportable;
  });
}

function canAutoReportSelectedProcess() {
  return reportMode === 'auto' && !serialBackfillMode &&
    isNormalReportProcessSelectable(getSelectedReportProcess());
}

function getUnavailableReportMessage(order) {
  var currentOrder = order || curOrder || {};
  var currentName = currentOrder.current_process && currentOrder.current_process.process_name;
  var candidates = (currentOrder.processes || []).filter(function(process) {
    return !!process.serial_backfill_reportable;
  });
  if (currentOrder.serial_backfill_selection_source === 'position_auto' && candidates.length) {
    return '已按当前岗位匹配补报工序“' + candidates[0].process_name + '”，请确认提交';
  }
  if (currentOrder.serial_backfill_selection_source === 'none' && currentOrder.serial_backfill_message) {
    return currentOrder.serial_backfill_message;
  }
  if (currentOrder.serial_backfill_selection_source === 'position_manual' && candidates.length) {
    return currentOrder.serial_backfill_message || '当前岗位有多个可补报工序，请选择本次工序';
  }
  if (candidates.length) {
    var candidateNames = candidates.map(function(process) { return process.process_name; }).join('、');
    return '当前工序为“' + (currentName || '未知') + '”，请选择“' + candidateNames + '”进行补报';
  }
  return currentOrder.process_selection_message ||
    (currentName ? '当前工序为“' + currentName + '”，当前账号没有可报工工序' : '当前没有可报工序');
}

function focusFirstBackfillCandidate() {
  setTimeout(function() {
    var candidate = $('order-body').querySelector('[data-backfill-candidate="true"]');
    if (candidate && candidate.scrollIntoView) {
      candidate.scrollIntoView({ behavior: 'smooth', block: 'center' });
      candidate.focus({ preventScroll: true });
    }
  }, 100);
}

function selectReportProcess(processId) {
  var process = (curOrder && curOrder.processes || []).find(function(item) {
    return String(item.process_id) === String(processId) && isReportProcessSelectable(item);
  });
  if (!process) return;
  var useBackfill = !isNormalReportProcessSelectable(process) && !!process.serial_backfill_reportable;
  renderOrder(curOrder, process.process_id, useBackfill);
  var maximum = curSerial ? 1 : (process.max_report_quantity || 0);
  $('rpt-qty').value = maximum;
  switchMode('manual');
  updateReportBtn();
}

function currentLocalDateTime() {
  var now = new Date();
  var local = new Date(now.getTime() - now.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 16);
}

function updateBackfillFields() {
  var fields = $('serial-backfill-fields');
  if (fields) fields.style.display = serialBackfillMode ? 'block' : 'none';
  if (serialBackfillMode) setReportType('normal');
}

function exitSerialBackfill() {
  if (!curOrder) return;
  serialBackfillMode = false;
  renderOrder(curOrder);
  var process = getSelectedReportProcess();
  $('rpt-qty').value = curSerial ? 1 : (process ? process.max_report_quantity || 0 : 0);
  switchMode('manual');
}

// ── 报工模式 ─────────────────────────────────
function switchMode(mode) {
  if (mode === 'auto' && serialBackfillMode && curOrder) {
    serialBackfillMode = false;
    renderOrder(curOrder);
  }
  reportMode = mode;
  $('mode-auto').classList.toggle('active', mode === 'auto');
  $('mode-manual').classList.toggle('active', mode === 'manual');
  $('report-form').style.display = (mode === 'manual' ? 'block' : 'none');
  updateReportBtn();
}

function setReportType(type) {
  if (serialBackfillMode && type !== 'normal') {
    toast('跨工序补报仅支持正常报工');
    return;
  }
  reportType = type;
  ['normal','scrap','rework'].forEach(function(t) {
    $('rtype-' + t).classList.toggle('active', t === type);
  });
  $('reason-row').style.display = (type === 'normal') ? 'none' : 'block';
  updateReportBtn();
}

function updateReportBtn() {
  const btn = $('btn-report');
  if (curOrder && curOrder.completion_focus_warning && curOrder.completion_focus_warning.blocking) {
    btn.disabled = true;
    btn.textContent = '集中完工强拦截：请先处理前序订单';
    btn.className = 'btn-report blocked';
    return;
  }
  var qty = parseInt($('rpt-qty').value) || 0;
  var selectedProcess = getSelectedReportProcess();
  if (
    reportType === 'normal' &&
    (!selectedProcess || (
      serialBackfillMode
        ? !selectedProcess.serial_backfill_reportable
        : !isNormalReportProcessSelectable(selectedProcess)
    ))
  ) {
    btn.disabled = true;
    btn.textContent = getUnavailableReportMessage();
    btn.className = 'btn-report blocked';
    return;
  }
  if (serialBackfillMode) {
    btn.disabled = false;
    btn.textContent = '提交“' + (selectedProcess.process_name || '') + '”补报申请';
    btn.className = 'btn-report';
    return;
  }
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

if ($('rpt-qty')) { $('rpt-qty').addEventListener('input', updateReportBtn); }

// ── 提交报工 ─────────────────────────────────
function doReport() {
  if (!curOrder || !curProcId) { toast('订单信息不完整'); return; }
  var selectedProcess = getSelectedReportProcess();
  if (
    !selectedProcess ||
    (serialBackfillMode
      ? !selectedProcess.serial_backfill_reportable
      : !isNormalReportProcessSelectable(selectedProcess))
  ) {
    switchMode('manual');
    toast(getUnavailableReportMessage(), 3200);
    return;
  }
  if (serialBackfillMode) {
    var currentName = curOrder.current_process && curOrder.current_process.process_name || '未知';
    if (!window.confirm('工件当前工序为“' + currentName + '”，即将补报“' + (selectedProcess.process_name || '') + '”，是否继续？')) {
      updateReportBtn();
      return;
    }
  }
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
  if (serialBackfillMode) {
    body.serial_backfill = true;
  }

  api.mobileReport(body)
  .then(function(d) {
    showReportSuccess(body, d || {});
  })
  .catch(function(e) {
    btn.disabled = false;
    updateReportBtn();
    if (e && (e.domainCode === 'quality_evaluation_required' || e.action === 'open_quality_evaluation')) {
      toast(e.message || '请先完成必评任务', 3200);
      openRequiredQualityEvaluation(body, e);
      return;
    }
    toast((e && e.message) || '网络异常');
  });
}

function showReportSuccess(body, response) {
  const qty = body.quantity || 1;
  const isBackfill = !!response.serial_backfill;
  const label = isBackfill ? '序列号跨工序补报' : (reportType === 'normal' ? '正常报工' : reportType === 'scrap' ? '报废' : '返修');
  const selectedProcess = getSelectedReportProcess();
  const selectedProcessName = selectedProcess ? selectedProcess.process_name : '';
  $('ok-title').textContent = isBackfill ? '补报申请已提交' : '报工成功!';
  $('ok-msg').textContent = isBackfill
    ? '等待审批通过后生效'
    : (curOrder.order_no || '') + ' · ' + selectedProcessName;
  $('ok-detail').innerHTML =
    '<div>📦 订单: ' + esc(curOrder.order_no || '') + '</div>' +
    '<div>⚙️ 工序: ' + esc(selectedProcessName) + '</div>' +
    '<div>📊 数量: ' + qty + ' 件</div>' +
     '<div>🏷️ 类型: ' + label + '</div>' +
    (isBackfill ? '<div>🕒 申请时间: 系统自动记录</div>' : '') +
    '<div>👤 操作人: ' + esc(response.worker ? response.worker.name : (user() ? user().name : '未知')) + '</div>' +
    ((response.quality_evaluation_pending_count || 0) > 0
      ? '<div class="success-quality-tip">待处理质量评价：' + response.quality_evaluation_pending_count + ' 条</div>'
      : '');
  show('ok');
  if ((response.quality_evaluation_pending_count || 0) > 0 && response.quality_evaluation_auto_open !== false) {
    var doneButton = document.querySelector('.btn-done');
    if (doneButton) doneButton.textContent = '立即完成质量评价';
    setTimeout(function() {
      openQualityEvaluationCenter();
      if (doneButton) doneButton.textContent = '继续扫码';
    }, 900);
  }
}
