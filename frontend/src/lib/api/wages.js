import { request, buildQuery, uploadFile } from './client.js'

export const wagesApi = {
  // ========== 工资 ==========
  listWages:        (params) => request('GET', '/api/wages' + buildQuery(params)),
}
