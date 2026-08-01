// Shared QR-System API client.
const BASE = ''

function apiError(response, payload, fallbackMessage) {
  const body = payload && typeof payload === 'object' ? payload : {}
  const error = new Error(body.error || fallbackMessage)
  error.code = response.status
  error.status = response.status
  error.domainCode = body.code || ''
  error.action = body.action || ''
  error.details = body.details || {}
  error.payload = body
  return error
}

async function parseApiResponse(response) {
  const text = await response.text()
  let payload = {}
  if (text) {
    try {
      payload = JSON.parse(text)
    } catch (_) {
      payload = { error: text }
    }
  }

  if (response.status === 401) {
    window.dispatchEvent(new CustomEvent('auth:expired'))
    throw apiError(response, payload, '\u767b\u5f55\u5df2\u8fc7\u671f')
  }
  if (!response.ok || payload.error) {
    const fallback = response.status === 409
      ? '\u6570\u636e\u51b2\u7a81'
      : `\u670d\u52a1\u5668\u9519\u8bef(${response.status})`
    throw apiError(response, payload, fallback)
  }
  return payload
}

export async function request(method, url, data) {
  const opts = {
    method,
    headers: {},
    credentials: 'same-origin'
  }
  if (data && method !== 'GET') {
    opts.headers['Content-Type'] = 'application/json'
    opts.body = JSON.stringify(data)
  }
  const response = await fetch(BASE + url, opts)
  return parseApiResponse(response)
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
  const response = await fetch(BASE + url, {
    method: 'POST',
    body: formData,
    credentials: 'same-origin'
  })
  return parseApiResponse(response)
}
