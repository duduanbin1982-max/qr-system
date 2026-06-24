<!-- InventoryList.vue -->
<template>
<div style="padding:var(--space-6)">
    <!-- ====== 统计栏（统一 summary-bar 风格）====== -->
    <div class="summary-bar">
      <div class="summary-item"><span class="s-icon">📦</span><div><div class="s-val">{{ stats.total_items }}</div><div class="s-label">库存品类</div></div></div>
      <div class="summary-item"><span class="s-icon">📊</span><div><div class="s-val text-primary">{{ stats.total_quantity || totalQty }}</div><div class="s-label">库存总量</div></div></div>
      <div class="summary-item"><span class="s-icon">💎</span><div><div class="s-val" style="color:var(--primary)">{{ inventoryValue.toLocaleString() }}</div><div class="s-label">库存总值</div></div></div>
      <div class="summary-item"><span class="s-icon">📥</span><div><div class="s-val text-success">{{ stats.today_in }}</div><div class="s-label">今日入库</div></div></div>
      <div class="summary-item"><span class="s-icon">📤</span><div><div class="s-val text-warning">{{ stats.today_out }}</div><div class="s-label">今日出库</div></div></div>
      <div class="summary-item"><span class="s-icon">⚠️</span><div><div class="s-val" :style="{color: stats.low_stock > 0 ? 'var(--danger)' : 'var(--success)'}">{{ stats.low_stock }}</div><div class="s-label">低库存预警</div></div></div>
    </div>
    <!-- ====== 主内容卡片 ====== -->
    <div class="card" style="border-radius:var(--radius-lg);overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.06),0 4px 16px rgba(0,0,0,0.04)">
      <div class="card-header" style="background:var(--bg-table-stripe);border-bottom:1px solid var(--bg-hover);padding:var(--space-4) 20px">
        <h3 style="font-size:var(--text-lg);font-weight:700;color:var(--text-primary);display:flex;align-items:center;gap:var(--space-2)">
          <span style="display:inline-flex;align-items:center;justify-content:center;width:32px;height:32px;background:linear-gradient(135deg,var(--primary),var(--primary-accent));border-radius:var(--radius-md);font-size:var(--text-lg)">🏗️</span>
          库存管理
        </h3>
        <div style="display:flex;gap:var(--space-3);align-items:center;flex-wrap:wrap">
          <div style="display:flex;align-items:center;background:var(--bg-hover);border-radius:var(--radius-md);padding:0 12px;transition:all 0.2s;border:1px solid transparent">
            <span style="color:var(--text-placeholder);font-size:var(--text-base)">🔍</span>
            <input class="form-input" v-model="searchKeyword" placeholder="搜索型号 / 名称…" @keyup.enter="load" style="border:none;background:transparent;outline:none;padding:var(--space-2) 8px;font-size:var(--text-sm);width:170px;box-shadow:none">
          </div>
          <label style="display:flex;align-items:center;gap:5px;font-size:var(--text-xs);color:var(--text-placeholder);cursor:pointer;white-space:nowrap;padding:6px 10px;background:#FFF;border-radius:var(--radius-md);border:1px solid var(--border-light)">
            <input type="checkbox" v-model="lowStockOnly" @change="load" style="accent-color:var(--danger);width:14px;height:14px"> 仅低库存
          </label>
          <select class="form-input" v-model="locationFilter" @change="load" style="border:1px solid var(--border-light);border-radius:var(--radius-md);padding:var(--space-2) 12px;font-size:var(--text-xs);background:white;cursor:pointer;width:110px">
            <option value="">📍 全部库位</option>
            <option v-for="loc in locations" :key="loc" :value="loc">{{ loc }}</option>
          </select>
          <div style="display:flex;gap:var(--space-2)">
            <button class="btn" style="padding:var(--space-2) 14px;font-size:var(--text-xs);background:var(--bg-hover);color:var(--text-secondary);border:1px solid var(--border-light);border-radius:var(--radius-md);cursor:pointer;font-weight:500" @click="load">🔍 搜索</button>
            <button class="btn" style="padding:var(--space-2) 14px;font-size:var(--text-xs);background:var(--bg-hover);color:var(--text-secondary);border:1px solid var(--border-light);border-radius:var(--radius-md);cursor:pointer;font-weight:500" @click="doABC">🏷️ ABC</button>
            <button class="btn" style="padding:var(--space-2) 14px;font-size:var(--text-xs);background:var(--bg-hover);color:var(--text-secondary);border:1px solid var(--border-light);border-radius:var(--radius-md);cursor:pointer;font-weight:500" @click="loadLogs()">📋 流水</button>
            <button class="btn" style="padding:var(--space-2) 14px;font-size:var(--text-xs);background:var(--bg-hover);color:var(--text-secondary);border:1px solid var(--border-light);border-radius:var(--radius-md);cursor:pointer;font-weight:500" @click="loadTurnover">📊 周转</button>
            <button class="btn" style="padding:var(--space-2) 14px;font-size:var(--text-xs);background:var(--bg-hover);color:var(--text-secondary);border:1px solid var(--border-light);border-radius:var(--radius-md);cursor:pointer;font-weight:500" @click="doCount">🔢 盘点</button>
            <button class="btn" style="padding:var(--space-2) 14px;font-size:var(--text-xs);background:var(--bg-hover);color:var(--text-secondary);border:1px solid var(--border-light);border-radius:var(--radius-md);cursor:pointer;font-weight:500" @click="exportExcel">📥导出</button>
            <button class="btn" style="padding:var(--space-2) 16px;font-size:var(--text-xs);background:linear-gradient(135deg,var(--primary),var(--primary));color:#FFF;border:none;border-radius:var(--radius-md);cursor:pointer;font-weight:600;box-shadow:0 2px 6px rgba(99,102,241,0.35)" @click="openAdd" v-if="canCreate">+ 新增库存</button>
          </div>
        </div>
      </div>
      <div class="card-body" style="padding:0">
        <div class="table-wrap" style="border-radius:0">
          <table v-if="items.length" class="data-table" style="min-width:850px;margin:0">
            <thead>
              <tr style="background:var(--bg-table-header)">
                <th style="min-width:100px;font-size:var(--text-xs);text-transform:uppercase;letter-spacing:0.5px;color:var(--text-muted)">产品名称</th>
                <th style="min-width:90px;font-size:var(--text-xs);text-transform:uppercase;letter-spacing:0.5px;color:var(--text-muted)">订单号</th>
                <th style="min-width:80px;font-size:var(--text-xs);text-transform:uppercase;letter-spacing:0.5px;color:var(--text-muted)">客户</th>
                <th style="min-width:110px;font-size:var(--text-xs);text-transform:uppercase;letter-spacing:0.5px;color:var(--text-muted)">产品型号</th>
                <th style="min-width:80px;font-size:var(--text-xs);text-transform:uppercase;letter-spacing:0.5px;color:var(--text-muted)">规格</th>
                <th style="width:55px;text-align:center;font-size:var(--text-xs);text-transform:uppercase;letter-spacing:0.5px;color:var(--text-muted)">ABC</th>
                <th style="width:80px;text-align:center;font-size:var(--text-xs);text-transform:uppercase;letter-spacing:0.5px;color:var(--text-muted)">数量</th>
                <th style="width:80px;text-align:center;font-size:var(--text-xs);text-transform:uppercase;letter-spacing:0.5px;color:var(--text-muted)">安全库存</th>
                <th style="min-width:80px;font-size:var(--text-xs);text-transform:uppercase;letter-spacing:0.5px;color:var(--text-muted)">存放位置</th>
                <th style="width:55px;text-align:center;font-size:var(--text-xs);text-transform:uppercase;letter-spacing:0.5px;color:var(--text-muted)">单位</th>
                <th style="width:195px;text-align:center;font-size:var(--text-xs);text-transform:uppercase;letter-spacing:0.5px;color:var(--text-muted);white-space:nowrap">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in items" :key="item.id" class="inv-row" :class="{'inv-row-low': item.is_low}" @click="loadLogs(item.id)" style="cursor:pointer">
                <td style="font-weight:500">{{ item.product_name || '-' }}</td>
                <td><code style="font-size:var(--text-xs-alt)">{{ item.order_no || '-' }}</code></td>
                <td style="font-size:var(--text-xs)">{{ item.customer || '-' }}</td>
                <td>
                  <div style="display:flex;align-items:center;gap:var(--space-2)">
                    <span :style="{display:'inline-block',width:8,height:8,borderRadius:'50%',background: item.is_low ? 'var(--danger)' : 'var(--success)',flexShrink:0}"></span>
                    <code style="font-size:var(--text-xs);font-weight:600;color:var(--text-primary)">{{ item.product_model }}</code>
                  </div>
                </td>
                <td style="font-size:var(--text-xs);color:var(--text-placeholder)">{{ item.specification || '-' }}</td>
                <td style="text-align:center">
                  <span v-if="item.category" class="badge" :class="item.category==='A'?'badge-danger':item.category==='B'?'badge-warning':'badge-success'" style="font-size:var(--text-2xs);font-weight:700">{{ item.category }}</span>
                  <span v-else style="color:var(--text-placeholder);font-size:var(--text-2xs)">-</span>
                </td>
                <td style="text-align:center">
                  <span style="display:inline-block;font-weight:700;font-size:15px;min-width:28px;padding:var(--space-1) 8px;border-radius:var(--radius-sm)" :style="{background: item.is_low ? 'var(--danger-light)' : 'var(--success-light)', color: item.is_low ? 'var(--danger)' : 'var(--success)'}">{{ item.quantity }}</span>
                </td>
                <td style="text-align:center;font-size:var(--text-xs);color:var(--text-placeholder)">
                  <span v-if="item.safe_stock" style="display:inline-block;background:var(--bg-hover);padding:1px 8px;border-radius:var(--radius-md);font-size:var(--text-xs-alt)">{{ item.safe_stock }}</span>
                  <span v-else>-</span>
                </td>
                <td style="font-size:var(--text-xs);color:var(--text-placeholder)">
                  <span v-if="item.location" style="display:inline-flex;align-items:center;gap:var(--space-1)">📍 {{ item.location }}</span>
                  <span v-else>-</span>
                </td>
                <td style="text-align:center;font-size:var(--text-xs);font-weight:500;color:var(--text-placeholder)">{{ item.unit }}</td>
                <td style="text-align:center">
                  <div class="inv-actions" @click.stop>
                    <button v-if="canEdit" class="inv-btn inv-btn-in" @click="openMove(item, 'in')" title="入库">
                      <span>📥</span><span>入库</span>
                    </button>
                    <button v-if="canEdit" class="inv-btn inv-btn-out" @click="openMove(item, 'out')" title="出库">
                      <span>📤</span><span>出库</span>
                    </button>
                    <button class="inv-btn inv-btn-edit" @click="openEdit(item)" v-if="canEdit" title="编辑">
                      <span>✏️</span>
                    </button>
                    <button class="inv-btn inv-btn-del" @click="del(item)" v-if="canDelete" title="删除">
                      <span>🗑️</span>
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
          <div v-else style="text-align:center;padding:60px 20px">
            <div style="font-size:48px;margin-bottom:var(--space-3);opacity:0.4">🏗️</div>
            <div style="font-size:var(--text-base);color:var(--text-placeholder);margin-bottom:6px">暂无库存数据</div>
            <div style="font-size:var(--text-xs);color:var(--border)">点击「+ 新增库存」添加第一条记录</div>
          </div>
        </div>
      </div>
    </div>
    <!-- 新增/编辑模态框 -->
    <div v-if="showModal" class="modal-overlay" >
      <div class="modal" style="max-width:550px">
        <div class="modal-header">
          <span>{{ modalEdit ? '编辑库存' : '新增库存' }}</span>
          <span class="modal-close" @click="showModal=false">&times;</span>
        </div>
        <div class="modal-body">
          <div class="form-row">
            <div class="form-col" style="flex:2"><div class="form-group"><label>产品型号 *</label><input class="form-input" v-model="form.product_model" :disabled="modalEdit" placeholder="唯一标识"></div></div>
            <div class="form-col" style="flex:1"><div class="form-group"><label>关联订单</label><select class="form-input" v-model="form.order_id"><option value="">-- 无 --</option><option v-for="o in orderOptions" :key="o.id" :value="o.id">{{ o.order_no }} {{ o.product_name }}</option></select></div></div>
            <div class="form-col" style="flex:1"><div class="form-group"><label>单位</label><input class="form-input" v-model="form.unit" placeholder="件"></div></div>
          </div>
          <div class="form-row">
            <div class="form-col"><div class="form-group"><label>产品名称</label><input class="form-input" v-model="form.product_name" placeholder="名称"></div></div>
            <div class="form-col"><div class="form-group"><label>规格</label><input class="form-input" v-model="form.specification" placeholder="规格"></div></div>
          </div>
          <div class="form-row">
            <div class="form-col" v-if="!modalEdit"><div class="form-group"><label>初始数量</label><input class="form-input" v-model.number="form.quantity" type="number" min="0"></div></div>
            <div class="form-col"><div class="form-group"><label>安全库存</label><input class="form-input" v-model.number="form.safe_stock" type="number" min="0"></div></div>
            <div class="form-col"><div class="form-group"><label>存放位置</label><input class="form-input" v-model="form.location" placeholder="如：A区-3号架"></div></div>
          </div>
          <div class="form-group"><label>备注</label><input class="form-input" v-model="form.remark" placeholder="备注"></div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-default" @click="showModal=false">取消</button>
          <button class="btn btn-primary" @click="save">保存</button>
        </div>
      </div>
    </div>
    <!-- 出入库模态框 -->
    <div v-if="showMoveModal" class="modal-overlay" >
      <div class="modal" style="max-width:400px">
        <div class="modal-header">
          <span>{{ moveType === 'in' ? '📥 入库' : '📤 出库' }} — {{ moveTarget?.product_model }}</span>
          <span class="modal-close" @click="showMoveModal=false">&times;</span>
        </div>
        <div class="modal-body" style="text-align:center">
          <p style="color:var(--text-placeholder);margin-bottom:var(--space-4)">当前库存：<strong>{{ moveTarget?.quantity }}</strong> {{ moveTarget?.unit }}</p>
          <div class="form-group" v-if="moveType==='in'" style="margin-bottom:var(--space-3)">
            <label>关联订单</label>
            <select class="form-input" v-model="moveOrderId" style="text-align:center">
              <option value="">-- 无 --</option>
              <option v-for="o in orderOptions" :key="o.id" :value="o.id">{{ o.order_no }} {{ o.product_name }}</option>
            </select>
          </div>
          <div class="form-group">
            <label>{{ moveType === 'in' ? '入库' : '出库' }}数量</label>
            <input class="form-input" v-model.number="moveQty" type="number" min="1" style="text-align:center;font-size:24px;font-weight:700;width:150px;margin:0 auto" autofocus @keyup.enter="doMove">
          </div>
        </div>
        <div class="modal-footer" style="justify-content:center">
          <button class="btn btn-default" @click="showMoveModal=false">取消</button>
          <button class="btn" :class="moveType === 'in' ? 'btn-success' : 'btn-warning'" @click="doMove" style="min-width:100px">
            {{ moveType === 'in' ? '确认入库' : '确认出库' }}
          </button>
        </div>
      </div>
    </div>
    <!-- 流水日志 -->
    <div v-if="showLogs" class="modal-overlay" >
      <div class="modal" style="max-width:1500px">
        <div class="modal-header">
          <span>📋 库存流水</span>
          <div style="display:flex;gap:var(--space-2);align-items:center">
            <button class="btn btn-default btn-sm" @click="window.open('/api/inventory/logs/export','_blank')" style="font-size:var(--text-xs)">📥导出</button>
            <span class="modal-close" @click="showLogs=false">&times;</span>
          </div>
        </div>
        <div class="modal-body">
          <div v-if="logsLoading" style="text-align:center;padding:40px">⏳ 加载中...</div>
          <table v-else-if="logs.length" class="data-table">
            <thead><tr><th style="min-width:150px">时间</th><th style="min-width:130px">型号</th><th style="min-width:60px">类型</th><th style="min-width:60px">数量</th><th style="min-width:80px">操作人</th><th style="min-width:180px">备注</th></tr></thead>
            <tbody>
              <tr v-for="l in logs" :key="l.id">
                <td style="font-size:var(--text-xs);white-space:nowrap">{{ l.created_at }}</td>
                <td style="white-space:nowrap"><code style="font-size:var(--text-xs-alt)">{{ l.product_model }}</code></td>
                <td><span class="badge" :class="l.type==='in'?'badge-success':'badge-warning'" style="font-size:var(--text-xs-alt)">{{ l.type==='in'?'入库':'出库' }}</span></td>
                <td style="font-weight:600" :style="{color: l.type==='in'?'var(--success)':'var(--danger)'}">{{ l.type==='in'?'+':'-' }}{{ l.quantity }}</td>
                <td style="font-size:var(--text-sm);white-space:nowrap">{{ l.operator_name || '-' }}</td>
                <td style="font-size:var(--text-xs);color:var(--text-placeholder);white-space:nowrap">{{ l.remark || '-' }}</td>
              </tr>
            </tbody>
          </table>
          <p v-else style="text-align:center;color:var(--text-muted);padding:40px">暂无流水记录</p>
        </div>
      </div>
    </div>

    <!-- 周转率模态框 -->
    <div v-if="showTurnover" class="modal-overlay" >
      <div class="modal" style="max-width:700px">
        <div class="modal-header">
          <span>📊 库存周转分析</span>
          <span class="modal-close" @click="showTurnover=false">&times;</span>
        </div>
        <div class="modal-body">
          <div v-if="turnoverLoading" style="text-align:center;padding:40px">⏳ 加载中...</div>
          <table v-else-if="turnoverData.length" class="data-table">
            <thead><tr><th>产品型号</th><th>当前库存</th><th>月出库</th><th>月周转率</th><th>状态</th></tr></thead>
            <tbody>
              <tr v-for="t in turnoverData" :key="t.id">
                <td><code style="font-size:var(--text-xs-alt)">{{ t.product_model }}</code></td>
                <td style="text-align:center;font-weight:600">{{ t.current_stock }}</td>
                <td style="text-align:center">{{ t.total_out || 0 }}</td>
                <td style="text-align:center">{{ t.turnover_rate || '-' }}</td>
                <td><span class="badge" :class="t.total_out===0?'badge-danger':t.turnover_rate<0.5?'badge-warning':'badge-success'" style="font-size:var(--text-2xs)">{{ t.total_out===0?'滞销':t.turnover_rate<0.5?'慢动':'正常' }}</span></td>
              </tr>
            </tbody>
          </table>
          <p v-else style="text-align:center;color:var(--text-muted);padding:40px">暂无数据</p>
        </div>
      </div>
    </div>
  </div>
</template>
<script>
import { useInventory } from '@/composables/useInventory.js'

export default {
  setup() {
    return useInventory()
  }
}
</script>
