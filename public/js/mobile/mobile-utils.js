'use strict';

// ═══════════════════════════════════════════
//  扫码报工系统 — 手机扫码模块 v3
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
  var old = document.querySelector('.qr-toast');
  if (old) old.remove();
  var t = document.createElement('div');
  t.className = 'qr-toast';
  var txt = String(msg || ''); // allow full message + '...';
  t.textContent = txt;
  t.style.cssText = 'position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);display:inline-block;width:fit-content;max-width:340px;background:rgba(0,0,0,.85);color:#fff;padding:10px 18px;border-radius:10px;font-size:16px;text-align:center;word-break:break-all;line-height:1.3;z-index:99999;pointer-events:none;';
  document.body.appendChild(t);
  setTimeout(function() { t.style.opacity = '0'; t.style.transition = 'opacity .25s'; setTimeout(function() { t.remove(); }, 300); }, ms || 2000);
}

// Auth: dual channel — httpOnly cookie (primary) + Bearer token (fallback).
// phone browsers may drop non-Secure cookies on HTTPS; Bearer is backup.
function token()  { var u = user(); if (u && u.token) return u.token; var m = document.cookie.match(/(?:^|;\s*)qr_token=([^;]*)/); return m ? m[1] : ''; }
function user()   {
  if (window.__qr_user) return window.__qr_user;
  try { var u = JSON.parse(sessionStorage.getItem('qr_user')); if (u) { window.__qr_user = u; return u; } } catch(e) {}
  return null;
}

function show(id) {
  const screens = document.querySelectorAll('.screen');
  for (var i = 0; i < screens.length; i++) screens[i].classList.remove('active');
  var el = $('s-' + id); if (el) el.classList.add('active');
}