'use strict';

var qualityRules = { low_score_threshold: 60, issue_tags: [] };

function loadQualityEvaluationCount() {
  var badge = $('quality-pending-badge');
  if (!badge || !user()) return;
  api.qualityEvaluationTasks({ status: 'pending', per_page: 1 })
    .then(function(result) {
      var count = result.pending_count == null ? (result.total || 0) : result.pending_count;
      badge.textContent = count > 99 ? '99+' : String(count);
      badge.classList.toggle('empty', count === 0);
    })
    .catch(function() { badge.textContent = '0'; badge.classList.add('empty'); });
}

function openQualityEvaluationCenter() {
  show('quality-evaluation');
  loadQualityEvaluationTasks();
}

function loadQualityEvaluationTasks() {
  var list = $('quality-task-list');
  if (!list) return;
  list.innerHTML = '<div class="quality-empty">正在加载评价任务...</div>';
  Promise.all([
    api.qualityEvaluationTasks({ status: 'pending', per_page: 200 }),
    api.qualityEvaluationRules()
  ]).then(function(results) {
    qualityRules = results[1] || qualityRules;
    renderQualityEvaluationTasks(results[0].items || []);
    var badge = $('quality-pending-badge');
    if (badge) {
      badge.textContent = String(results[0].pending_count || 0);
      badge.classList.toggle('empty', !(results[0].pending_count || 0));
    }
  }).catch(function(error) {
    list.innerHTML = '<div class="quality-empty error">' + esc(error.message || '评价任务加载失败') + '</div>';
  });
}

function renderQualityEvaluationTasks(tasks) {
  var list = $('quality-task-list');
  if (!tasks.length) {
    list.innerHTML = '<div class="quality-empty"><strong>暂无待评价任务</strong><span>完成下道工序报工后，符合条件的上游工序会出现在这里。</span></div>';
    return;
  }
  var groups = {};
  tasks.forEach(function(task) {
    var key = task.trigger_work_record_id;
    if (!groups[key]) groups[key] = [];
    groups[key].push(task);
  });
  list.innerHTML = Object.keys(groups).map(function(key) {
    var rows = groups[key];
    var first = rows[0];
    return '<section class="quality-group">' +
      '<div class="quality-group-head"><div><strong>' + esc(first.order_no || '') + '</strong><span>' + esc(first.product_name || '') + '</span></div>' +
      '<div>' + esc(first.serial_no || '订单模式') + '</div></div>' +
      rows.map(renderQualityTaskCard).join('') + '</section>';
  }).join('');
}

function renderQualityTaskCard(task) {
  var dimensions = qualityRules.dimensions || [
    { key: 'processing_quality', label: '加工质量' },
    { key: 'dimensional_accuracy', label: '尺寸或精度' },
    { key: 'appearance_quality', label: '外观质量' },
    { key: 'process_continuity', label: '工序可接续性' },
    { key: 'cleanliness_protection', label: '清洁及防护' }
  ];
  var tags = qualityRules.issue_tags || [];
  return '<article class="quality-task" data-task-id="' + task.id + '">' +
    '<div class="quality-task-head"><div><span class="quality-required ' + (task.is_required ? 'required' : '') + '">' + (task.is_required ? '必评' : '选评') + '</span>' +
    '<strong>' + esc(task.target_process_name || '') + '</strong></div><span class="quality-score good">100分</span></div>' +
    '<div class="quality-meta">被评价：' + esc(task.target_user_name || '工序整体') + ' · 接手工序：' + esc(task.evaluator_process_name || '') + '</div>' +
    '<div class="quality-dimensions">' + dimensions.map(function(dimension) {
      return '<label><span>' + esc(dimension.label) + '</span><select data-dimension="' + dimension.key + '">' +
        [5,4,3,2,1].map(function(score) { return '<option value="' + score + '">' + score + '分</option>'; }).join('') +
        '</select></label>';
    }).join('') + '</div>' +
    '<div class="quality-tags"><span>问题标签（低分必填）</span><div>' + tags.map(function(tag) {
      return '<label><input type="checkbox" data-issue-tag value="' + esc(tag) + '"> ' + esc(tag) + '</label>';
    }).join('') + '</div></div>' +
    '<textarea data-comment rows="2" placeholder="补充说明，可填写具体位置、现象和影响"></textarea>' +
    '<div class="quality-actions"><button data-action="perfect" class="quality-secondary">全部5分</button><button data-action="submit" class="quality-primary">提交评价</button></div>' +
    '</article>';
}

function qualityCardScore(card) {
  var selects = card.querySelectorAll('select[data-dimension]');
  var total = 0;
  for (var index = 0; index < selects.length; index++) total += parseInt(selects[index].value) || 0;
  return selects.length ? Math.round(total / selects.length * 20) : 0;
}

function updateQualityCardScore(card) {
  var score = qualityCardScore(card);
  var scoreNode = card.querySelector('.quality-score');
  if (scoreNode) {
    scoreNode.textContent = score + '分';
    scoreNode.className = 'quality-score ' + (score >= 80 ? 'good' : score >= 60 ? 'warn' : 'bad');
  }
}

function handleQualityScoreChange(event) {
  if (!event.target.matches('select[data-dimension]')) return;
  var card = event.target.closest('.quality-task');
  if (card) updateQualityCardScore(card);
}

function handleQualityTaskClick(event) {
  var action = event.target.getAttribute('data-action');
  if (!action) return;
  var card = event.target.closest('.quality-task');
  if (!card) return;
  if (action === 'perfect') {
    card.querySelectorAll('select[data-dimension]').forEach(function(select) { select.value = '5'; });
    updateQualityCardScore(card);
    return;
  }
  if (action === 'submit') submitQualityTask(card, event.target);
}

function submitQualityTask(card, button) {
  var payload = { task_id: parseInt(card.getAttribute('data-task-id')) };
  card.querySelectorAll('select[data-dimension]').forEach(function(select) {
    payload[select.getAttribute('data-dimension')] = parseInt(select.value);
  });
  payload.issue_tags = Array.from(card.querySelectorAll('input[data-issue-tag]:checked')).map(function(input) { return input.value; });
  payload.comment = (card.querySelector('[data-comment]').value || '').trim();
  var score = qualityCardScore(card);
  if (score < (qualityRules.low_score_threshold || 60) && !payload.issue_tags.length && !payload.comment) {
    toast('低分评价请勾选问题标签或填写说明');
    return;
  }
  button.disabled = true;
  button.textContent = '提交中...';
  api.submitQualityEvaluations(payload).then(function(result) {
    var item = result.items && result.items[0];
    toast(item && item.status === 'pending_verification' ? '评价已提交，等待质量核验' : '评价已提交');
    card.remove();
    if (!$('quality-task-list').querySelector('.quality-task')) loadQualityEvaluationTasks();
    else loadQualityEvaluationCount();
  }).catch(function(error) {
    toast(error.message || '评价提交失败');
    button.disabled = false;
    button.textContent = '提交评价';
  });
}
