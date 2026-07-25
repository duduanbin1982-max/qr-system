import { request } from './client.js'

export const scanApi = {
  scan: (data) => request('POST', '/api/scan', data),
  report: (data) => request('POST', '/api/report', data),
  decodeMobileCode: (code) => request('GET', '/api/mobile/decode/' + encodeURIComponent(code)),
}
