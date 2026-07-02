"use strict";
// ═══════════════════════════════════════════
//  移动端 API 请求封装 — 与前端 api.js 保持一致
// ═══════════════════════════════════════════

const API = "/api";

function token() {
  if (typeof user === "function") {
    var u = user();
    if (u && u.token) return u.token;
  }
  try {
    var stored = JSON.parse(sessionStorage.getItem("qr_user"));
    if (stored && stored.token) return stored.token;
  } catch(e) {}
  var m = document.cookie.match(/(?:^|;\s*)qr_token=([^;]*)/);
  return m ? m[1] : "";
}

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
  if (response.status === 401) {
    if (window.handleAuthExpired) window.handleAuthExpired();
    var authError = new Error((payload && payload.error) || "登录已过期");
    authError.code = 401;
    throw authError;
  }
  if (!response.ok || (payload && payload.error)) {
    var err = new Error((payload && payload.error) || "服务器错误(" + response.status + ")");
    err.code = response.status;
    throw err;
  }
  return payload;
}

async function apiRequest(method, url, data) {
  var opts = {
    method: method,
    credentials: "same-origin",
    headers: {}
  };
  var t = token();
  if (t) opts.headers["Authorization"] = "Bearer " + t;
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
  handoffPending: function(params) { return apiRequest("GET", "/handoff-reviews/pending" + buildMobileQuery(params)); },
  createHandoffReview: function(data) { return apiRequest("POST", "/handoff-reviews", data); },
  report: function(data) { return apiRequest("POST", "/report", data); },

  // 质量检验
  submitInspection: function(data) { return apiRequest("POST", "/inspection/submit", data); },

  // 认证
  login: function(data) { return apiRequest("POST", "/auth/login", data); },
  logout: function() { return apiRequest("POST", "/auth/logout"); },
  changePassword: function(data) { return apiRequest("POST", "/auth/change-password", data); },
  authInfo: function() { return apiRequest("GET", "/auth/info"); },
  personalStats: function() { return apiRequest("GET", "/personal/stats"); }
};
