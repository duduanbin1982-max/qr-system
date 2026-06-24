"use strict";
// ═══════════════════════════════════════════
//  移动端 API 请求封装 — 与前端 api.js 保持一致
// ═══════════════════════════════════════════

const API = "/api";

function token() {
  var u = user();
  if (u && u.token) return u.token;
  var m = document.cookie.match(/(?:^|;\s*)qr_token=([^;]*)/);
  return m ? m[1] : "";
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
  var r = await fetch(API + url, opts);
  var d = await r.json();
  if (r.status === 401) {
    if (window.handleAuthExpired) window.handleAuthExpired();
    throw new Error("登录已过期");
  }
  if (d.error) {
    throw new Error(d.error);
  }
  return d;
}

// 便捷方法
var api = {
  get: function(url) { return apiRequest("GET", url); },
  post: function(url, data) { return apiRequest("POST", url, data); },
  put: function(url, data) { return apiRequest("PUT", url, data); },
  del: function(url) { return apiRequest("DELETE", url); },

  // 扫码相关
  decodeQR: function(code) { return apiRequest("GET", "/mobile/decode/" + code); },
  mobileScan: function(data) { return apiRequest("POST", "/mobile/scan", data); },
  mobileReport: function(data) { return apiRequest("POST", "/mobile/report", data); },
  report: function(data) { return apiRequest("POST", "/report", data); },

  // 质量检验
  submitInspection: function(data) { return apiRequest("POST", "/inspection/submit", data); },

  // 认证
  login: function(data) { return apiRequest("POST", "/auth/login", data); },
  logout: function() { return apiRequest("POST", "/auth/logout"); },
  changePassword: function(data) { return apiRequest("POST", "/auth/change-password", data); },
  personalStats: function() { return apiRequest("GET", "/personal/stats"); }
};
