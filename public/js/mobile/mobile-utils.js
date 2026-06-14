'use strict';

// ═══════════════════════════════════════════
//  扫码报工系统 — 手机扫码模块 v3
//  双引擎：BarcodeDetector (硬件加速) + jsQR (纯JS通用降级)
// ═══════════════════════════════════════════

const API = '/api';

// ── 状态 ──────────────────────────────────
let curOrder   = null;
let curProcId  = null;
let curSerial  = '';
let camStream  = null;
let scanTimer  = null;
let lastCode   = '';
let lastTime   = 0;
let reportMode = 'auto';
let reportType = 'normal';
let bd         = null;  // BarcodeDetector 实例
let flashOn    = false;

// ── 工具函数 ──────────────────────────────
const $ = function(id) { return document.getElementById(id); };

function esc(s) {
  if (!s) return '';
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

function toast(msg, ms) {
  const old = document.querySelector('.toast');
  if (old) old.remove();
  const t = document.createElement('div');
  t.className = 'toast';
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(function() { t.style.opacity = '0'; setTimeout(function() { t.remove(); }, 300); }, ms || 2000);
}

// Auth: dual channel — httpOnly cookie (primary) + Bearer token (fallback).
// phone browsers may drop non-Secure cookies on HTTPS; Bearer is backup.
function token()  { return ''; /* token via httpOnly cookie, no longer in sessionStorage */ }
function user()   {
  if (window.__qr_user) return window.__qr_user;
  try { var u = JSON.parse(sessionStorage.getItem('qr_user')); if (u) { window.__qr_user = u; return u; } } catch(e) {}
  return null;
}

function show(id) {
  const screens = document.querySelectorAll('.screen');
  for (var i = 0; i < screens.length; i++) screens[i].classList.remove('active');
  $('s-' + id).classList.add('active');
}