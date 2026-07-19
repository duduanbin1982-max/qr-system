// Mobile Inspection Page v4 - Serial vs Order mode aware
(function() {
  var orderData = null;
  var selectedProcess = null;
  var selectedProcessId = null;
  var scanMode = 'order'; // 'serial' or 'order'
  var scanSerialNo = '';
  var SCORE_ITEMS = [
    { key: 'dimension_accuracy', label: '尺寸精度', max: 30 },
    { key: 'process_conformance', label: '孔位/工艺符合度', max: 25 },
    { key: 'appearance_quality', label: '外观质量', max: 20 },
    { key: 'function_impact', label: '装配/功能影响', max: 15 },
    { key: 'documentation_other', label: '标识/资料/其他', max: 10 }
  ];

  function getToken() {
    // Try sessionStorage first (set by mobile-order.js redirect), then cookie
    try {
      var t = sessionStorage.getItem('iq_token') || '';
      if (t) { sessionStorage.removeItem('iq_token'); return t; }
    } catch(e) {}
    try {
      var u = JSON.parse(sessionStorage.getItem('qr_user'));
      if (u && u.token) return u.token;
    } catch(e) {}
    var m = document.cookie.match(/(?:^|;\s*)qr_token=([^;]*)/);
    return m ? m[1] : '';
  }

  function esc(s) {
    if (!s) return '';
    var d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  }

  function showMsg(msg, type) {
    var el = document.getElementById('msg');
    el.textContent = msg;
    el.className = 'msg ' + (type || 'info');
  }

  function clearMsg() {
    document.getElementById('msg').className = 'msg';
  }

  function enableButtons(enable) {
    document.getElementById('btn-pass').disabled = !enable;
    document.getElementById('btn-rework').disabled = !enable;
    document.getElementById('btn-scrap').disabled = !enable;
  }

  function resultLabel(result) {
    return result === 'pass' ? '合格' : result === 'rework' ? '返修' : result === 'scrap' ? '报废' : '-';
  }

  function clampNumber(value, min, max) {
    var n = Number(value);
    if (!isFinite(n)) n = max;
    return Math.max(min, Math.min(max, n));
  }

  function readScorePayload(finalResult) {
    var detail = {};
    var total = 0;
    SCORE_ITEMS.forEach(function(item) {
      var input = document.querySelector('[data-score-key="' + item.key + '"]');
      var score = clampNumber(input ? input.value : item.max, 0, item.max);
      if (input) input.value = score;
      total += score;
      detail[item.key] = { label: item.label, max: item.max, score: score };
    });
    total = Math.round(total * 10) / 10;
    var defectLevel = document.getElementById('defectLevel').value || '';
    var suggested = defectLevel === 'critical' ? 'scrap' : (total >= 85 ? 'pass' : (total >= 60 ? 'rework' : 'scrap'));
    var overrideReason = (document.getElementById('overrideReason').value || '').trim();
    var defectDesc = (document.getElementById('defectDesc').value || '').trim();
    var finalValue = finalResult || suggested;
    if (finalValue !== suggested && !overrideReason) {
      document.getElementById('overrideReason').style.display = 'block';
      throw new Error('最终判定与系统建议不一致，请填写原因');
    }
    return {
      score_total: total,
      score_detail: detail,
      defect_level: defectLevel,
      defect_items: defectDesc ? [{ level: defectLevel, description: defectDesc }] : [],
      suggested_result: suggested,
      final_result: finalValue,
      override_reason: overrideReason,
      notes: defectDesc
    };
  }

  function updateScoreSuggestion() {
    try {
      var payload = readScorePayload(null);
      document.getElementById('scoreTotal').textContent = payload.score_total;
      document.getElementById('suggestedResult').textContent = resultLabel(payload.suggested_result);
      document.getElementById('overrideReason').style.display = 'none';
    } catch(e) {
      document.getElementById('scoreTotal').textContent = '-';
    }
  }

  function selectProcess(el) {
    var items = document.querySelectorAll('.proc-item');
    items.forEach(function(item) { item.classList.remove('selected'); });
    el.classList.add('selected');
    selectedProcess = el.getAttribute('data-process');
    selectedProcessId = el.getAttribute('data-process-id');
    document.getElementById('selectedProcess').textContent = selectedProcess;
    enableButtons(true);
    clearMsg();
  }

  function submitResult(result) {
    if (!orderData) { showMsg('订单信息缺失', 'error'); return; }

    if (!selectedProcess) {
      var procs = orderData.processes || [];
      if (procs.length === 1) {
        selectedProcess = procs[0].process_name || procs[0].name || "" || '';
        document.getElementById('selectedProcess').textContent = selectedProcess;
        selectedProcessId = procs[0].process_id || procs[0].id || '';
      } else {
        showMsg('请先选择上方工序', 'error');
        return;
      }
    }

    var scoring;
    try {
      scoring = readScorePayload(result);
    } catch(e) {
      showMsg(e.message, 'error');
      return;
    }

    var data = {
      process_id: selectedProcessId,
      order_id: orderData.id,
      order_no: orderData.order_no || '',
      product_code: orderData.product_code || orderData.product_name || '',
      process_name: selectedProcess,
      result: result,
      rework_process: result === 'rework' ? selectedProcess : '',
      serial_no: scanSerialNo,
      remark: document.getElementById('remark').value || ''
    };
    Object.keys(scoring).forEach(function(key) { data[key] = scoring[key]; });

    enableButtons(false);

    api.submitInspection(data)
    .then(function(d) {
      var label = result === 'pass' ? '合格' : result === 'rework' ? '返修' : '报废';
      showMsg('已提交: ' + label, 'success');
      enableButtons(true);
      setTimeout(function() { window.location.href = '/mobile.html'; }, 1500);
    })
    .catch(function(e) {
      showMsg(e.message || '提交失败，请重试', 'error');
      enableButtons(true);
    });
  }

  function init() {
    var params = new URLSearchParams(window.location.search);
    var code = params.get('code') || sessionStorage.getItem('iq_code') || '';

    if (!code) {
      document.getElementById('info').innerHTML = '';
      showMsg('缺少扫码信息，请返回重新扫码', 'error');
      return;
    }

    var token = getToken();
    if (!token) {
      document.getElementById('info').innerHTML = '';
      showMsg('登录已过期，请返回重新登录', 'error');
      return;
    }

    document.getElementById('btn-pass').addEventListener('click', function() { submitResult('pass'); });
    document.getElementById('btn-rework').addEventListener('click', function() { submitResult('rework'); });
    document.getElementById('btn-scrap').addEventListener('click', function() { submitResult('scrap'); });
    document.querySelectorAll('.score-input').forEach(function(input) {
      input.addEventListener('input', updateScoreSuggestion);
    });
    document.getElementById('defectLevel').addEventListener('change', updateScoreSuggestion);
    updateScoreSuggestion();

    document.getElementById('info').innerHTML = '<div class="loading">查询中...</div>';

    api.mobileScan({ code: code })
    .then(function(d) {
      if (!d.order) { throw new Error('未获取到订单信息'); }
      orderData = d.order;

      // Determine mode
      if (d.item && d.item.serial_no) {
        scanMode = 'serial';
        scanSerialNo = d.item.serial_no;
      } else {
        scanMode = 'order';
        scanSerialNo = '';
      }

      var modeBadge = scanMode === 'serial'
        ? '<span style="display:inline-block;background:#eef2ff;color:#6366f1;padding:2px 8px;border-radius:4px;font-size:12px;margin-left:6px">序列号模式</span>'
        : '<span style="display:inline-block;background:#fef3c7;color:#d97706;padding:2px 8px;border-radius:4px;font-size:12px;margin-left:6px">订单模式</span>';

      var serialLine = scanMode === 'serial'
        ? '<br>序列号: <strong>' + esc(scanSerialNo) + '</strong>'
        : '';

      document.getElementById('info').innerHTML =
        '<strong>' + esc(d.order.product_name || d.order.product_code || '') + '</strong>' + modeBadge + '<br>' +
        '订单: ' + esc(d.order.order_no || '') + ' | 数量: ' + (d.order.quantity || 0) + ' | 客户: ' + esc(d.order.customer || '') +
        serialLine;

      renderProcessList();
    })
    .catch(function(e) {
      document.getElementById('info').innerHTML = '';
      showMsg(e.message || '网络错误，请重试', 'error');
    });
  }

  function renderProcessList() {
    var processes = orderData ? (orderData.processes || []) : [];
    var section = document.getElementById('processSection');
    var list = document.getElementById('processList');

    section.style.display = 'block';

    if (!processes.length) {
      list.innerHTML = '<div style="padding:20px;text-align:center;color:#999">无工序数据</div>';
      return;
    }

    var html = '';
    processes.forEach(function(p) {
      var pname = p.process_name || p.name || '';
      var completed = p.completed || 0;
      var isCurrent = orderData && orderData.current_process && orderData.current_process.process_name === pname;
      html += '<div class="proc-item' + (isCurrent ? ' selected' : '') + '" data-process="' + esc(pname) + '" data-process-id="' + (p.process_id || p.id || '') + '">' +
        '<div class="dot"></div>' +
        '<span class="pname">' + esc(pname) + '</span>' +
        '<span class="pstat">' + (isCurrent ? '当前工序 · ' : '') + '已完成 ' + completed + '</span>' +
        '</div>';
    });
    list.innerHTML = html;

    // Bind events
    var items = list.querySelectorAll('.proc-item');
    items.forEach(function(item) {
      item.addEventListener('click', function() { selectProcess(item); });
    });

    // Auto-select current process for serial mode
    if (scanMode === 'serial' && orderData.current_process && orderData.current_process.process_name) {
      var cpName = orderData.current_process.process_name;
      items.forEach(function(item) {
        if (item.getAttribute('data-process') === cpName) {
          selectProcess(item);
        }
      });
    } else if (processes.length === 1) {
      selectProcess(items[0]);
    }
  }

  document.addEventListener('DOMContentLoaded', init);
})();
