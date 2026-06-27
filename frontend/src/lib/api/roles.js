import { request } from './client.js'

export const rolesApi = {
  // ========== 角色 ==========
  listRoleGroups:   ()       => request('GET', '/api/role-groups'),
  createRoleGroup:  (data)   => request('POST', '/api/role-groups', data),
  updateRoleGroup:  (id,data)=> request('PUT',  '/api/role-groups/' + id, data),
  deleteRoleGroup:  (id)     => request('DELETE', '/api/role-groups/' + id),
  listRoles:        ()       => request('GET', '/api/roles'),
  createRole:       (data)   => request('POST', '/api/roles', data),
  updateRole:       (id,data)=> request('PUT',  '/api/roles/' + id, data),
  deleteRole:       (id)     => request('DELETE', '/api/roles/' + id),
  getPermissions:   ()       => request('GET', '/api/permissions'),
}
