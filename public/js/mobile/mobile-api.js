"use strict";
// ═══════════════════════════════════════════
//  移动端 API 请求封装 — 与前端 api.js 保持一致
// ═══════════════════════════════════════════

const API = "/api";

function buildMobileQuery(params) {
  if (!params) return "";
  if (typeof params === "string") return params ? "?" + params.replace(/^\?/, "") : "";
  var pairs = [];
  Object.keys(params).forEach(function(key) {
    var value = params[key];
    if (value === "" || value == null) return;
    pairs.push(encodeURIComponent(key) + "=" + encodeURIComponent(value));
  });
  return pairs.length ? "?" + pairs.join("&") : "";
}

async function parseApiResponse(response) {
  var payload = null;
  var text = await response.text();
  if (text) {
    try { payload = JSON.parse(text); }
    catch(e) { payload = { error: text }; }
  } else {
    payload = {};
  }
  function responseError(fallbackMessage) {
    var body = payload && typeof payload === "object" ? payload : {};
    var error = new Error(body.error || fallbackMessage);
    error.code = response.status;
    error.status = response.status;
    error.domainCode = body.code || "";
    error.action = body.action || "";
    error.details = body.details || {};
    error.payload = body;
    return error;
  }
  if (response.status === 401) {
    if (window.handleAuthExpired) window.handleAuthExpired();
    throw responseError("登录已过期");
  }
  if (!response.ok || (payload && payload.error)) {
    throw responseError(
      response.status === 409 ? "数据冲突" : "服务器错误(" + response.status + ")"
    );
  }
  return payload;
}

async function apiRequest(method, url, data) {
  var opts = {
    method: method,
    credentials: "same-origin",
    headers: {}
  };
  if (data && method !== "GET") {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(data);
  }
  var response = await fetch(API + url, opts);
  return parseApiResponse(response);
}

// 便捷方法
var api = {
  get: function(url) { return apiRequest("GET", url); },
  post: function(url, data) { return apiRequest("POST", url, data); },
  put: function(url, data) { return apiRequest("PUT", url, data); },
  del: function(url) { return apiRequest("DELETE", url); },

  // 扫码相关
  decodeQR: function(code) { return apiRequest("GET", "/mobile/decode/" + encodeURIComponent(code)); },
  mobileScan: function(data) { return apiRequest("POST", "/mobile/scan", data); },
  mobileReport: function(data) { return apiRequest("POST", "/mobile/report", data); },
  qualityEvaluationTasks: function(params) { return apiRequest("GET", "/process-quality-evaluations/tasks" + buildMobileQuery(params)); },
  skipQualityEvaluationTask: function(id, data) { return apiRequest("POST", "/process-quality-evaluations/tasks/" + id + "/skip", data); },
  submitQualityEvaluations: function(data) { return apiRequest("POST", "/process-quality-evaluations", data); },
  myQualityEvaluations: function(params) { return apiRequest("GET", "/process-quality-evaluations/mine" + buildMobileQuery(params)); },
  createQualityEvaluationAppeal: function(id, data) { return apiRequest("POST", "/process-quality-evaluations/" + id + "/appeals", data); },
  myQualityEvaluationAppeals: function(params) { return apiRequest("GET", "/process-quality-evaluations/appeals" + buildMobileQuery(params)); },
  qualityEvaluationRules: function() { return apiRequest("GET", "/process-quality-evaluations/rules"); },
  report: function(data) { return apiRequest("POST", "/report", data); },

  // 质量检验
  submitInspection: function(data) { return apiRequest("POST", "/inspection/submit", data); },

  // 认证
  login: function(data) { return apiRequest("POST", "/auth/login", data); },
  logout: function() { return apiRequest("POST", "/auth/logout"); },
  changePassword: function(data) { return apiRequest("POST", "/auth/change-password", data); },
  authInfo: function() { return apiRequest("GET", "/auth/info"); },
  activePosition: function() { return apiRequest("GET", "/auth/active-position"); },
  setActivePosition: function(data) { return apiRequest("PUT", "/auth/active-position", data); },
  personalStats: function() { return apiRequest("GET", "/personal/stats"); }
};
