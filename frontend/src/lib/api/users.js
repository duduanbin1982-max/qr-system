import { request, buildQuery, uploadFile } from './client.js'

export const usersApi = {
  // ========== 员工 ==========
  listUsers:        (params) => request('GET', '/api/users' + buildQuery(params)),
  createUser:       (data)   => request('POST', '/api/users', data),
  updateUser:       (id,data)=> request('PUT',  '/api/users/' + id, data),
  deleteUser:       (id)     => request('DELETE', '/api/users/' + id),
  restoreUser:      (id)     => request('POST', '/api/users/' + id + '/restore'),
  permanentDeleteUser: (id)     => request('DELETE', '/api/users/' + id + '/permanent'),
  resetPassword:    (id,data)=> request('POST', '/api/users/' + id + '/reset-password', data),
  unlockUser:       (id)     => request('POST', '/api/users/' + id + '/unlock'),
}
