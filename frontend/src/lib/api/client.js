// Shared QR-System API client.
const BASE = ''

export async function request(method, url, data) {
  const opts = {
    method,
    headers: {},
    credentials: "include"
  }
  // Token is sent via httpOnly cookie (auto-attached by browser).
  // No localStorage or Authorization header needed.
  if (data && method !== 'GET') {
    opts.headers['Content-Type'] = 'application/json'
    opts.body = JSON.stringify(data)
  }
  const r = await fetch(BASE + url, opts)
  if (r.status === 401) {
    const err = new Error('\u767b\u5f55\u5df2\u8fc7\u671f')
    err.code = 401
    window.dispatchEvent(new CustomEvent('auth:expired'))
    throw err
  }
  const d = await r.json()
  if (r.status === 409) {
    const err = new Error(d.error || '\u6570\u636e\u51b2\u7a81')
    err.code = 409
    throw err
  }
  if (d.error) {
    const err = new Error(d.error)
    err.code = r.status
    throw err
  }
  return d
}

// Brooks R3 fix: Unified error handler ? eliminates repeated showToast patterns.
export function handleApiError(e, fallbackMsg) {
  const msg = (e && e.message) ? e.message : (fallbackMsg || '\u64cd\u4f5c\u5931\u8d25')
  return { error: true, message: msg }
}

export function buildQuery(params) {
  if (!params) return ''
  const qs = Object.entries(params)
    .filter(([_, v]) => v !== '' && v != null)
    .map(([k, v]) => encodeURIComponent(k) + '=' + encodeURIComponent(v))
    .join('&')
  return qs ? '?' + qs : ''
}

export async function uploadFile(url, formData) {
  // Cookie-only auth: httpOnly cookie auto-attached by browser.
  // No manual Authorization header needed.
  const opts = { method: 'POST', body: formData }
  const r = await fetch(BASE + url, opts)
  if (r.status === 401) {
    const err = new Error('\u767b\u5f55\u5df2\u8fc7\u671f')
    err.code = 401
    window.dispatchEvent(new CustomEvent('auth:expired'))
    throw err
  }
  const d = await r.json()
  if (d.error) {
    const err = new Error(d.error)
    err.code = r.status
    throw err
  }
  return d
}
