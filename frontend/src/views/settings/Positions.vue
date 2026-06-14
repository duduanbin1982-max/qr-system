<!-- Positions.vue -->
<template>
<div>
    <div>
      <div class="card">
        <div class="card-header">
          <h3>💼 岗位管理</h3>
          <button class="btn btn-primary btn-sm" @click="openAddPosition">+ 新增岗位</button>
        </div>
        <div class="card-body">
          <div v-if="positionLoading" style="text-align:center;padding:40px;color:var(--text-placeholder)">⏳ 加载中...</div>
          <div v-else>
            <div v-if="positions.length" class="table-wrap">
              <table class="data-table">
<thead><tr>
  <th style="width:50px">#</th>
  <th>岗位名称</th>
  <th>描述</th>
  <th>关联工序</th>
  <th style="width:80px">状态</th>
  <th style="width:100px;text-align:center;white-space:nowrap">操作</th>
</tr></thead>
                <tbody>
                  <tr v-for="(p, idx) in positions" :key="p.id">
                    <td style="text-align:center"><span class="badge" style="background:var(--primary-light);color:var(--primary-dark);min-width:28px;text-align:center">{{ idx+1 }}</span></td>
                    <td style="font-weight:500">{{ p.name }}</td>
                    <td style="color:var(--text-placeholder)">{{ p.description || '-' }}</td>
                    <td>
                      <span v-if="p.processes && p.processes.length">
                        <span v-for="proc in p.processes" :key="proc.process_id">
                          <span class="badge" style="background:var(--success-light);color:var(--success-dark);border:1px solid var(--success-lighter);margin-right:4px;margin-bottom:3px;display:inline-block;font-size:var(--text-xs-alt)">{{ proc.process_name }}</span>
                        </span>
                      </span>
                      <span v-else style="color:var(--text-placeholder);font-size:var(--text-xs)">未设置</span>
                    </td>
                    <td><span class="badge" :class="p.status==='active'?'completed':'pending'">{{ p.status==='active'?'启用':'停用' }}</span></td>
                    <td style="text-align:center;white-space:nowrap">
                      <button class="o-abtn edit" @click="openEditPosition(p)">✏️</button>
                      <button class="o-abtn del" @click="deletePosition(p.id)">🗑️</button>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div v-else class="empty"><div class="empty-text">暂无岗位，点击"新增岗位"创建</div></div>
          </div>
        </div>
      </div>
    </div>

    <!-- Position Modal -->
    <div v-if="showPositionModal" class="modal-overlay" >
      <div class="modal">
        <div class="modal-header"><span>{{ positionModalEdit ? '编辑岗位' : '新增岗位' }}</span><span class="modal-close" @click="showPositionModal=false">&times;</span></div>
        <div class="modal-body">
          <div class="form-group"><label>岗位名称 *</label><input class="form-input" v-model="positionForm.name" placeholder="如：焊接工、质检员"></div>
          <div class="form-group"><label>描述</label><input class="form-input" v-model="positionForm.description" placeholder="岗位职责描述"></div>
          <div class="form-group"><label>状态</label><select class="form-input" v-model="positionForm.status"><option value="active">启用</option><option value="inactive">停用</option></select></div>
          <div class="form-group"><label>可报工工序</label>
            <div style="display:flex;flex-wrap:wrap;gap:var(--space-2);margin-top:8px">
              <label v-for="proc in allProcesses" :key="proc.id"
                :style="{display:'flex',alignItems:'center',gap:'6px',padding:'6px 12px',borderRadius:'6px',cursor:'pointer',fontSize:'13px',border:'1px solid '+(positionForm.process_ids.includes(proc.id)?'var(--primary)':'var(--border-light)'),background:positionForm.process_ids.includes(proc.id)?'var(--primary-light)':'var(--bg-surface)',color:positionForm.process_ids.includes(proc.id)?'var(--primary-dark)':'var(--text-secondary)'}">
                <input type="checkbox" :checked="positionForm.process_ids.includes(proc.id)" @change="toggleProcessInPosition(proc.id)" style="accent-color:var(--primary)">
                {{ proc.process_name || proc.name }}
              </label>
            </div>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-default" @click="showPositionModal=false">取消</button>
          <button class="btn btn-primary" @click="savePosition">💾 保存</button>
        </div>
      </div>
    </div>
</div>
</template>

<script>
import { usePositions } from '@/composables/settings/usePositions.js'

export default {
  setup() {
    return usePositions()
  }
}
</script>