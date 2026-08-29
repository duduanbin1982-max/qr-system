'use strict';

var qualityRules = { low_score_threshold: 60, critical_score_threshold: 40, issue_tags: [], critical_issue_tags: [] };
var qualityViewMode = 'tasks';
var qualityNavigation = { returnTo: 'main', reportDraft: null, resumeNotice: '' };
var QUALITY_PAGE_SIZE = 50;
var qualityRequestSeq = 0;
var qualityTaskState = { page: 0, perPage: QUALITY_PAGE_SIZE, total: 0, pendingRequiredCount: 0, tasks: [], loading: false };
var qualityMineState = { recordPage: 0, recordPerPage: QUALITY_PAGE_SIZE, recordTotal: 0, records: [], appealPage: 0, appealPerPage: QUALITY_PAGE_SIZE, appealTotal: 0, appeals: [], loading: false };

function qualityHasMore(page, total, perPage) {
  return page > 0 && page * perPage < total;
}

function isCurrentQualityRequest(requestId, mode) {
  return requestId === qualityRequestSeq && qualityViewMode === mode;
}

function updateQualityEvaluationIndicator(result) {
  var badge = $('quality-pending-badge');
  var hint = $('quality-entry-hint');
  var count = result && result.pending_count == null ? (result.total || 0) : ((result && result.pending_count) || 0);
  var requiredCount = (result && result.pending_required_count) || 0;
  if (badge) {
    badge.textContent = count > 99 ? '99+' : String(count);
    badge.title = requiredCount ? '其中必评 ' + requiredCount + ' 条' : '暂无必评任务';
    badge.classList.toggle('empty', count === 0);
  }
  if (hint) {
    hint.textContent = requiredCount
      ? '待评价 ' + count + ' 条，其中必评 ' + requiredCount + ' 条'
      : (count ? '待评价 ' + count + ' 条，暂无必评' : '评价已接手工件的上游工序');
  }
}

function loadQualityEvaluationCount() {
  var badge = $('quality-pending-badge');
  if (!badge || !user()) return;
  api.qualityEvaluationTasks({ status: 'pending', per_page: 1 })
    .then(function(result) {
      updateQualityEvaluationIndicator(result);
    })
    .catch(function() { updateQualityEvaluationIndicator({ pending_count: 0, pending_required_count: 0 }); });
}

function openQualityEvaluationCenter(options) {
  options = options && options.returnTo ? options : {};
  qualityNavigation = {
    returnTo: options.returnTo === 'order' ? 'order' : 'main',
    reportDraft: options.reportDraft ? Object.assign({}, options.reportDraft) : null,
    resumeNotice: ''
  };
  qualityViewMode = 'tasks';
  updateQualityViewButtons();
  show('quality-evaluation');
  loadQualityEvaluationTasks();
}

function openRequiredQualityEvaluation(reportDraft) {
  if (camStream) closeCam();
  openQualityEvaluationCenter({ returnTo: 'order', reportDraft: reportDraft });
}

function resetQualityNavigation() {
  qualityNavigation = { returnTo: 'main', reportDraft: null, resumeNotice: '' };
}

function restoreBlockedReport(draft) {
  if (!curOrder || !curProcId) {
    resetQualityNavigation();
    goMain();
    return;
  }
  show('order');
  switchMode('manual');
  setReportType((draft && draft.report_type) || 'normal');
  if (draft && draft.quantity) $('rpt-qty').value = draft.quantity;
  if (draft && draft.remark) $('rpt-reason').value = draft.remark;
  updateReportBtn();
}

function closeQualityEvaluationCenter() {
  var navigation = qualityNavigation;
  resetQualityNavigation();
  if (navigation.returnTo === 'order') {
    restoreBlockedReport(navigation.reportDraft);
    return;
  }
  goMain();
}

function resumeBlockedReportWhenReady(tasks) {
  if (qualityNavigation.returnTo !== 'order') return false;
  var requiredTasks = tasks.filter(function(task) { return !!task.is_required; });
  if (requiredTasks.length) return false;
  var draft = qualityNavigation.reportDraft;
  var notice = qualityNavigation.resumeNotice;
  resetQualityNavigation();
  restoreBlockedReport(draft);
  toast(notice || '必评任务已完成，请确认后继续提交报工', 3200);
  return true;
}

function recoverStaleQualityTask(error) {
  var message = (error && error.message) || '评价任务已由其他人员处理，已刷新任务列表';
  if (qualityNavigation.returnTo === 'order') qualityNavigation.resumeNotice = message;
  toast(message, 3200);
  loadQualityEvaluationTasks();
}

function switchQualityView(mode) {
  qualityRequestSeq += 1;
  qualityTaskState.loading = false;
  qualityMineState.loading = false;
  qualityViewMode = mode === 'mine' ? 'mine' : 'tasks';
  updateQualityViewButtons();
  if (qualityViewMode === 'mine') loadMyQualityEvaluations();
  else loadQualityEvaluationTasks();
}

function updateQualityViewButtons() {
  document.querySelectorAll('[data-quality-view]').forEach(function(button) {
    button.classList.toggle('active', button.getAttribute('data-quality-view') === qualityViewMode);
  });
}

function loadQualityEvaluationTasks() {
  var append = arguments[0] && arguments[0].append === true;
  var list = $('quality-task-list');
  if (!list) return;
  if (append && (qualityTaskState.loading || !qualityHasMore(qualityTaskState.page, qualityTaskState.total, qualityTaskState.perPage))) return;
  var requestId = ++qualityRequestSeq;
  var page = append ? qualityTaskState.page + 1 : 1;
  qualityTaskState.loading = true;
  if (!append) {
    qualityTaskState = { page: 0, perPage: QUALITY_PAGE_SIZE, total: 0, pendingRequiredCount: 0, tasks: [], loading: true };
    list.innerHTML = '<div class="quality-empty">正在加载评价任务...</div>';
  }
  var requests = [api.qualityEvaluationTasks({ status: 'pending', page: page, per_page: QUALITY_PAGE_SIZE })];
  if (!append) requests.push(api.qualityEvaluationRules());
  Promise.all(requests).then(function(results) {
    if (!isCurrentQualityRequest(requestId, 'tasks')) return;
    var pageResult = results[0] || {};
    if (!append) qualityRules = results[1] || qualityRules;
    var items = pageResult.items || [];
    qualityTaskState.tasks = append ? qualityTaskState.tasks.concat(items) : items;
    qualityTaskState.page = Number(pageResult.page) || page;
    qualityTaskState.perPage = Number(pageResult.per_page) || QUALITY_PAGE_SIZE;
    qualityTaskState.total = Number(pageResult.total) || qualityTaskState.tasks.length;
    qualityTaskState.pendingRequiredCount = pageResult.pending_required_count == null ? 0 : Number(pageResult.pending_required_count);
    qualityTaskState.loading = false;
    renderQualityEvaluationTasks(qualityTaskState.tasks);
    updateQualityEvaluationIndicator(pageResult);
    var allLoaded = !qualityHasMore(qualityTaskState.page, qualityTaskState.total, qualityTaskState.perPage);
    if (pageResult.pending_required_count == null || qualityTaskState.pendingRequiredCount === 0 || allLoaded) {
      resumeBlockedReportWhenReady(qualityTaskState.tasks);
    }
  }).catch(function(error) {
    if (!isCurrentQualityRequest(requestId, 'tasks')) return;
    qualityTaskState.loading = false;
    list.innerHTML = '<div class="quality-empty error">' + esc(error.message || '评价任务加载失败') + '</div>';
  });
}

function loadMyQualityEvaluations() {
  var append = arguments[0] && arguments[0].append === true;
  var list = $('quality-task-list');
  if (!list) return;
  var recordsHaveMore = qualityHasMore(qualityMineState.recordPage, qualityMineState.recordTotal, qualityMineState.recordPerPage);
  var appealsHaveMore = qualityHasMore(qualityMineState.appealPage, qualityMineState.appealTotal, qualityMineState.appealPerPage);
  if (append && (qualityMineState.loading || (!recordsHaveMore && !appealsHaveMore))) return;
  var requestId = ++qualityRequestSeq;
  qualityMineState.loading = true;
  if (!append) {
    qualityMineState = { recordPage: 0, recordPerPage: QUALITY_PAGE_SIZE, recordTotal: 0, records: [], appealPage: 0, appealPerPage: QUALITY_PAGE_SIZE, appealTotal: 0, appeals: [], loading: true };
    list.innerHTML = '<div class="quality-empty">正在加载我的评价...</div>';
  }
  var specs = [];
  var recordPage = qualityMineState.recordPage + 1;
  var appealPage = qualityMineState.appealPage + 1;
  if (!append || recordsHaveMore) specs.push({ kind: 'records', promise: api.myQualityEvaluations({ page: recordPage, per_page: QUALITY_PAGE_SIZE }) });
  if (!append || appealsHaveMore) specs.push({ kind: 'appeals', promise: api.myQualityEvaluationAppeals({ scope: 'mine', page: appealPage, per_page: QUALITY_PAGE_SIZE }) });
  Promise.all(specs.map(function(spec) { return spec.promise; })).then(function(results) {
    if (!isCurrentQualityRequest(requestId, 'mine')) return;
    specs.forEach(function(spec, index) {
      var pageResult = results[index] || {};
      if (spec.kind === 'records') {
        qualityMineState.records = append ? qualityMineState.records.concat(pageResult.items || []) : (pageResult.items || []);
        qualityMineState.recordPage = Number(pageResult.page) || recordPage;
        qualityMineState.recordPerPage = Number(pageResult.per_page) || QUALITY_PAGE_SIZE;
        qualityMineState.recordTotal = Number(pageResult.total) || qualityMineState.records.length;
      } else {
        qualityMineState.appeals = append ? qualityMineState.appeals.concat(pageResult.items || []) : (pageResult.items || []);
        qualityMineState.appealPage = Number(pageResult.page) || appealPage;
        qualityMineState.appealPerPage = Number(pageResult.per_page) || QUALITY_PAGE_SIZE;
        qualityMineState.appealTotal = Number(pageResult.total) || qualityMineState.appeals.length;
      }
    });
    qualityMineState.loading = false;
    renderMyQualityEvaluations(qualityMineState.records, qualityMineState.appeals);
  }).catch(function(error) {
    if (!isCurrentQualityRequest(requestId, 'mine')) return;
    qualityMineState.loading = false;
    list.innerHTML = '<div class="quality-empty error">' + esc(error.message || '我的评价加载失败') + '</div>';
  });
}

function requiredQualityTaskFirst(left, right) {
  var requiredDifference = Number(!!right.task.is_required) - Number(!!left.task.is_required);
  return requiredDifference || left.sourceIndex - right.sourceIndex;
}

function requiredQualityGroupFirst(left, right) {
  var requiredDifference = Number(right.hasRequired) - Number(left.hasRequired);
  return requiredDifference || left.sourceIndex - right.sourceIndex;
}

function groupQualityEvaluationTasks(tasks) {
  var groups = [];
  var groupsByKey = {};
  tasks.forEach(function(task, sourceIndex) {
    var key = task.trigger_work_record_id == null
      ? 'task:' + task.id
      : 'work:' + task.trigger_work_record_id;
    var group = groupsByKey[key];
    if (!group) {
      group = { key: key, rows: [], hasRequired: false, sourceIndex: sourceIndex };
      groupsByKey[key] = group;
      groups.push(group);
    }
    group.rows.push({ task: task, sourceIndex: sourceIndex });
    group.hasRequired = group.hasRequired || !!task.is_required;
  });
  groups.forEach(function(group) {
    group.rows = group.rows.sort(requiredQualityTaskFirst).map(function(entry) { return entry.task; });
  });
  return groups.sort(requiredQualityGroupFirst);
}

function renderQualityEvaluationTasks(tasks) {
  var list = $('quality-task-list');
  if (!tasks.length) {
    list.innerHTML = '<div class="quality-empty"><strong>暂无待评价任务</strong><span>完成下道工序报工后，符合条件的上游工序会出现在这里。</span></div>';
    return;
  }
  var groups = groupQualityEvaluationTasks(tasks);
  list.innerHTML = groups.map(function(group) {
    var rows = group.rows;
    var first = rows[0];
    return '<section class="quality-group">' +
      '<div class="quality-group-head"><div><strong>' + esc(first.order_no || '') + '</strong><span>' + esc(first.product_name || '') + '</span></div>' +
      '<div>' + esc(first.serial_no || '订单模式') + '</div></div>' +
      rows.map(renderQualityTaskCard).join('') + '</section>';
  }).join('');
  renderQualityPager(list, qualityHasMore(qualityTaskState.page, qualityTaskState.total, qualityTaskState.perPage), 'load-more-quality-tasks', '加载更多待评价任务');
}

function renderQualityPager(list, hasMore, action, label) {
  if (!hasMore) return;
  list.insertAdjacentHTML('beforeend', '<button type="button" class="quality-load-more" data-action="' + action + '">' + label + '</button>');
}

function taskTemplate(task) {
  var snapshot = task.template_snapshot || {};
  return {
    name: snapshot.name || '通用评价模板',
    dimensions: snapshot.dimensions || qualityRules.dimensions || [],
    issue_tags: snapshot.issue_tags || qualityRules.issue_tags || [],
    critical_issue_tags: snapshot.critical_issue_tags || qualityRules.critical_issue_tags || [],
    low_score_threshold: snapshot.low_score_threshold == null ? qualityRules.low_score_threshold : snapshot.low_score_threshold
  };
}

function renderQualityTaskCard(task) {
  var template = taskTemplate(task);
  var criticalTags = {};
  template.critical_issue_tags.forEach(function(tag) { criticalTags[tag] = true; });
  var allTags = template.issue_tags.concat(template.critical_issue_tags).filter(function(tag, index, tags) {
    return tags.indexOf(tag) === index;
  });
  return '<article class="quality-task" data-task-id="' + task.id + '" data-low-threshold="' + template.low_score_threshold + '">' +
    '<div class="quality-task-head"><div><span class="quality-required ' + (task.is_required ? 'required' : '') + '">' + (task.is_required ? '必评' : '选评') + '</span>' +
    '<strong>' + esc(task.target_process_name || '') + '</strong></div><span class="quality-score good">100分</span></div>' +
    '<div class="quality-meta">' + esc(template.name) + ' · 接手工序：' + esc(task.evaluator_process_name || '') + '</div>' +
    '<div class="quality-identity-note">提交前隐藏被评价人员身份</div>' +
    '<div class="quality-dimensions">' + template.dimensions.map(function(dimension) {
      var optional = dimension.required === false;
      return '<label><span>' + esc(dimension.label) + (dimension.weight > 1 ? ' ×' + dimension.weight : '') + (optional ? '（选填）' : '') + '</span><select data-dimension="' + esc(dimension.key) + '" data-weight="' + (dimension.weight || 1) + '">' +
        (optional ? '<option value="">不适用</option>' : '') +
        [5,4,3,2,1].map(function(score) { return '<option value="' + score + '">' + score + '分</option>'; }).join('') +
        '</select></label>';
    }).join('') + '</div>' +
    '<div class="quality-tags"><span>问题标签（低分必填）</span><div>' + allTags.map(function(tag) {
      return '<label class="' + (criticalTags[tag] ? 'quality-critical-tag' : '') + '"><input type="checkbox" data-issue-tag value="' + esc(tag) + '"> ' + esc(tag) + (criticalTags[tag] ? '<em>严重</em>' : '') + '</label>';
    }).join('') + '</div></div>' +
    '<textarea data-comment rows="2" placeholder="补充说明，可填写具体位置、现象和影响"></textarea>' +
    '<div class="quality-actions"><button data-action="perfect" class="quality-secondary">全部5分</button>' +
    (task.is_required ? '' : '<button data-action="skip" class="quality-secondary">无问题跳过</button>') +
    '<button data-action="submit" class="quality-primary">提交评价</button></div>' +
    '</article>';
}

function qualityCardScore(card) {
  var selects = card.querySelectorAll('select[data-dimension]');
  var total = 0;
  var weights = 0;
  for (var index = 0; index < selects.length; index++) {
    var score = parseInt(selects[index].value);
    if (!score) continue;
    var weight = parseInt(selects[index].getAttribute('data-weight')) || 1;
    total += score * weight;
    weights += weight;
  }
  return weights ? Math.round(total / (5 * weights) * 100) : 0;
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
  var view = event.target.getAttribute('data-quality-view');
  if (view) { switchQualityView(view); return; }
  var action = event.target.getAttribute('data-action');
  if (!action) return;
  if (action === 'load-more-quality-tasks') { loadQualityEvaluationTasks({ append: true }); return; }
  if (action === 'load-more-quality-mine') { loadMyQualityEvaluations({ append: true }); return; }
  var card = event.target.closest('.quality-task, .quality-received-card');
  if (!card) return;
  if (action === 'perfect') {
    card.querySelectorAll('select[data-dimension]').forEach(function(select) { select.value = '5'; });
    updateQualityCardScore(card);
    return;
  }
  if (action === 'submit') submitQualityTask(card, event.target);
  if (action === 'skip') skipQualityTask(card, event.target);
  if (action === 'appeal') submitQualityAppeal(card, event.target);
}

function submitQualityTask(card, button) {
  var payload = { task_id: parseInt(card.getAttribute('data-task-id')), dimension_scores: {} };
  card.querySelectorAll('select[data-dimension]').forEach(function(select) {
    var score = parseInt(select.value);
    if (score) payload.dimension_scores[select.getAttribute('data-dimension')] = score;
  });
  payload.issue_tags = Array.from(card.querySelectorAll('input[data-issue-tag]:checked')).map(function(input) { return input.value; });
  payload.comment = (card.querySelector('[data-comment]').value || '').trim();
  var score = qualityCardScore(card);
  var threshold = parseInt(card.getAttribute('data-low-threshold')) || qualityRules.low_score_threshold || 60;
  if (score < threshold && !payload.issue_tags.length && !payload.comment) {
    toast('低分评价请勾选问题标签或填写说明');
    return;
  }
  button.disabled = true;
  button.textContent = '提交中...';
  api.submitQualityEvaluations(payload).then(function(result) {
    var item = result.items && result.items[0];
    toast(item && item.status === 'pending_verification' ? '评价已提交，等待质量核验' : '评价已提交');
    card.remove();
    if (qualityNavigation.returnTo === 'order' || !$('quality-task-list').querySelector('.quality-task')) loadQualityEvaluationTasks();
    else loadQualityEvaluationCount();
  }).catch(function(error) {
    if (error && (error.domainCode === 'quality_evaluation_task_stale' || error.action === 'refresh_quality_evaluation')) {
      recoverStaleQualityTask(error);
      return;
    }
    toast(error.message || '评价提交失败');
    button.disabled = false;
    button.textContent = '提交评价';
  });
}

function skipQualityTask(card, button) {
  if (!confirm('确认当前历史工序未发现问题并跳过选评吗？')) return;
  button.disabled = true;
  api.skipQualityEvaluationTask(parseInt(card.getAttribute('data-task-id')), { reason: '未发现历史工序问题' })
    .then(function() {
      toast('已跳过历史工序选评');
      card.remove();
      if (qualityNavigation.returnTo === 'order') loadQualityEvaluationTasks();
      else loadQualityEvaluationCount();
    })
    .catch(function(error) {
      if (error && (error.domainCode === 'quality_evaluation_task_stale' || error.action === 'refresh_quality_evaluation')) {
        recoverStaleQualityTask(error);
        return;
      }
      toast(error.message || '跳过失败');
      button.disabled = false;
    });
}

function renderMyQualityEvaluations(records, appeals) {
  var list = $('quality-task-list');
  var appealMap = {};
  appeals.forEach(function(appeal) {
    var current = appealMap[appeal.evaluation_id];
    if (!current || String(appeal.created_at || '') > String(current.created_at || '')) {
      appealMap[appeal.evaluation_id] = appeal;
    }
  });
  if (!records.length) {
    list.innerHTML = '<div class="quality-empty"><strong>暂无收到的评价</strong><span>明确归属到个人的工序评价会显示在这里。</span></div>';
    renderQualityPager(list,
      qualityHasMore(qualityMineState.recordPage, qualityMineState.recordTotal, qualityMineState.recordPerPage) || qualityHasMore(qualityMineState.appealPage, qualityMineState.appealTotal, qualityMineState.appealPerPage),
      'load-more-quality-mine', '加载更多评价记录');
    return;
  }
  list.innerHTML = records.map(function(row) {
    var appeal = appealMap[row.id];
    var issues = (row.issue_tags || []).concat(row.comment ? [row.comment] : []).join('；') || '无问题说明';
    var status = row.status === 'pending_verification' ? '待质量核验' : row.status === 'rejected' ? '已撤销' : '已确认';
    var appealText = appeal ? (appeal.status === 'pending' ? '申诉处理中' : appeal.status === 'accepted' ? '申诉成立' : '申诉不成立') : '';
    return '<article class="quality-received-card" data-evaluation-id="' + row.id + '">' +
      '<div class="quality-task-head"><strong>' + esc(row.target_process_name || '') + '</strong><span class="quality-score ' + (row.total_score >= 80 ? 'good' : row.total_score >= 60 ? 'warn' : 'bad') + '">' + row.total_score + '分</span></div>' +
      '<div class="quality-meta">' + esc(row.order_no || '') + ' · ' + esc(row.serial_no || '订单模式') + '</div>' +
      '<div class="quality-received-body">' + esc(issues) + '</div>' +
      '<div class="quality-received-status">' + esc(status) + (appealText ? ' · ' + esc(appealText) : '') + '</div>' +
      ((!appeal && row.status === 'confirmed') ? '<div class="quality-actions"><button data-action="appeal" class="quality-secondary">提出申诉</button></div>' : '') +
      '</article>';
  }).join('');
  renderQualityPager(list,
    qualityHasMore(qualityMineState.recordPage, qualityMineState.recordTotal, qualityMineState.recordPerPage) || qualityHasMore(qualityMineState.appealPage, qualityMineState.appealTotal, qualityMineState.appealPerPage),
    'load-more-quality-mine', '加载更多评价记录');
}

function submitQualityAppeal(card, button) {
  var reason = prompt('请填写申诉原因（至少5个字符）');
  if (!reason) return;
  button.disabled = true;
  api.createQualityEvaluationAppeal(parseInt(card.getAttribute('data-evaluation-id')), { reason: reason.trim() })
    .then(function() { toast('申诉已提交，待质量主管复核'); loadMyQualityEvaluations(); })
    .catch(function(error) { toast(error.message || '申诉提交失败'); button.disabled = false; });
}
