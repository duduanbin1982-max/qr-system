// Mobile Inspection Page v4 - Serial vs Order mode aware
(function() {
  var orderData = null;
  var selectedProcess = null;
  var selectedProcessId = null;
  var scanMode = 'order'; // 'serial' or 'order'
  var scanSerialNo = '';

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

    var token = getToken();
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

    enableButtons(false);

    fetch(API + '/inspection/submit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
      body: JSON.stringify(data)
    })
    .then(function(r) {
      if (!r.ok) {
        return r.json().then(function(d) { throw new Error(d.error || '提交失败(' + r.status + ')'); })
          .catch(function(e) { if (e.message) throw e; throw new Error('提交失败(' + r.status + ')'); });
      }
      return r.json();
    })
    .then(function(d) {
      if (d.error) { throw new Error(d.error); }
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

    document.getElementById('info').innerHTML = '<div class="loading">查询中...</div>';

    fetch(API + '/mobile/scan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
      body: JSON.stringify({ code: code })
    })
    .then(function(r) {
      if (!r.ok) {
        return r.json().then(function(d) {
          throw new Error(d.error || '服务器错误(' + r.status + ')');
        }).catch(function(e) {
          if (e.message && e.message.indexOf('服务器错误') === 0) throw e;
          throw new Error('服务器错误(' + r.status + ')');
        });
      }
      return r.json();
    })
    .then(function(d) {
      if (d.error) { throw new Error(d.error); }
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
