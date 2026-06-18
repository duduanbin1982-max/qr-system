<!-- ProductList.vue -->
<template>
<div style="padding:var(--space-6)">
    <div class="summary-bar">
      <div class="summary-item"><span class="s-icon">📦</span><div><div class="s-val">{{ products.length }}</div><div class="s-label">产品总数</div></div></div>
      <div class="summary-item"><span class="s-icon">🏗️</span><div><div class="s-val text-primary">{{ structCount }}</div><div class="s-label">结构件</div></div></div>
      <div class="summary-item"><span class="s-icon">🔧</span><div><div class="s-val text-success">{{ machCount }}</div><div class="s-label">机加工</div></div></div>
    </div>

    <div class="cat-tabs">
      <span class="cat-tab cat-tab-all" :class="{active: activeCat==='all'}" @click="switchCat('all')">📋 全部产品</span>
      <span class="cat-tab cat-tab-struct" :class="{active: activeCat==='结构件'}" @click="switchCat('结构件')">🔩 结构件产品</span>
      <span class="cat-tab cat-tab-mach" :class="{active: activeCat==='机加工'}" @click="switchCat('机加工')">⚙️ 机加工产品</span>
    </div>

    <div class="card">
      <div class="card-header">
        <h3>{{ pageTitle }}</h3>
        <div style="display:flex;gap:var(--space-2);align-items:center">
          <div class="search-box" style="background:var(--bg-hover);border-radius:var(--radius-md);display:flex;align-items:center;padding:0 10px">
            <span>🔍</span>
            <input class="form-input" v-model="searchKeyword" placeholder="搜索名称/型号/规格..." @keyup.enter="load" style="border:none;background:transparent;outline:none;padding:var(--space-2) 6px;font-size:var(--text-base);width:200px;box-shadow:none">
          </div>
          <button class="btn btn-default btn-sm" @click="load" style="white-space:nowrap">搜索</button>
          <button v-if="can('products:create')" class="btn btn-primary btn-sm" @click="openAdd" style="white-space:nowrap">+ 添加产品</button>
          <button v-if="can('products:create')" class="btn btn-success btn-sm" @click="triggerImport" style="white-space:nowrap">📥 导入Excel</button>
          <button v-if="can('products:delete')" class="btn btn-sm" :style="{whiteSpace:'nowrap',background:showTrash?'var(--danger)':'var(--bg-hover)',color:showTrash?'#fff':'var(--text-muted)',border:'1px solid '+(showTrash?'var(--danger)':'var(--border-light)'),borderRadius:'var(--radius-md)'}" @click="toggleTrash">🗑️ 回收站 <span v-if="trashedProducts.length" style="background:#fff;color:var(--danger);border-radius:10px;padding:0 6px;font-size:11px;margin-left:4px">{{ trashedProducts.length }}</span></button>
          <input type="file" ref="importFile" accept=".xlsx" style="display:none" @change="handleImport">
        </div>
      </div>
      <div class="card-body">
        <div class="table-wrap">
          <table v-if="products.length" class="data-table" style="min-width:900px">
            <thead>
              <tr>
                <th style="width:40px;text-align:center">#</th>
                <th style="min-width:120px">产品名称</th>
                <th style="min-width:160px">产品编码</th>
                <th style="min-width:80px">型号</th>
                <th>规格</th>
                <th style="width:85px;white-space:nowrap">分类</th>
                <th style="width:70px">重量(kg)</th>
                <th style="width:80px">单价(元)</th>
                <th style="width:100px;text-align:center">附件</th>
                <th style="width:80px;text-align:center">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(p, idx) in products" :key="p.id">
                <td style="text-align:center"><span class="row-num">{{ idx + 1 }}</span></td>
                <td style="font-weight:600">{{ p.product_name }}</td>
                <td><code style="font-size:var(--text-sm);font-weight:600;color:var(--primary);background:var(--primary-light);padding:3px 8px;border-radius:var(--radius-sm)">{{ p.product_code }}</code></td>
                <td>{{ p.model || '-' }}</td>
                <td style="font-size:var(--text-sm);color:var(--text-placeholder)">{{ p.spec || '-' }}</td>
                <td style="white-space:nowrap"><span class="badge" :class="p.category === '结构件' ? 'badge-info' : 'badge-warning'" style="font-size:var(--text-xs-alt)">{{ p.category || '-' }}</span></td>
                <td style="text-align:center">{{ p.weight || '-' }}</td>
                <td style="text-align:center;color:var(--success);font-weight:500">{{ p.price ? '¥' + p.price : '-' }}</td>
                <td style="text-align:center;vertical-align:middle">
                  <div v-if="p.thumbnail_id" style="cursor:pointer;display:inline-block" @click.stop="openThumbnail(p.thumbnail_id)" :title="'点击查看附件'">
                    <img :src="getThumbnailUrl(p.thumbnail_id)" style="width:48px;height:48px;border-radius:var(--radius-sm);object-fit:cover;border:1px solid var(--border-light)">
                  </div>
                  <span v-else-if="p.attachment_count" style="font-size:var(--text-xs);color:var(--text-placeholder)">{{ p.attachment_count }} 个附件</span>
                  <span v-else style="font-size:var(--text-xs);color:var(--border)">-</span>
                </td>
                <td style="text-align:center">
                  <div class="o-actions" style="justify-content:center">
                    <span v-if="canEdit" class="o-abtn o-edit" @click="openEdit(p)">✏️</span>
                    <span v-if="canDelete" class="o-abtn o-del" @click="del(p)">🗑️</span>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
          <div v-else class="empty-state">
            <div class="empty-icon">📦</div>
            <div class="empty-text">暂无产品数据</div>
          </div>
        </div>
      </div>
    </div>

    <!-- ====== 回收站弹窗 ====== -->
    <div class="modal-overlay" v-if="showTrash">
      <div class="modal" style="width:90vw;max-width:1100px;max-height:85vh;overflow-y:auto">
        <div class="modal-header">
          <h3>🗑️ 回收站（{{ trashedProducts.length }} 条）</h3>
          <span class="modal-close" @click="showTrash=false">&times;</span>
        </div>
        <div class="modal-body">
          <div class="table-wrap" v-if="trashedProducts.length">
            <table class="data-table" style="min-width:800px">
              <thead><tr><th>产品名称</th><th>产品编码</th><th>型号</th><th>分类</th><th>删除时间</th><th>操作</th></tr></thead>
              <tbody>
                <tr v-for="p in trashedProducts" :key="'trash-'+p.id" style="background:var(--bg-warning)">
                  <td><strong>{{ p.product_name }}</strong></td>
                  <td><code>{{ p.product_code }}</code></td>
                  <td>{{ p.model || '-' }}</td>
                  <td><span class="badge" :class="p.category==='结构件'?'badge-info':'badge-warning'">{{ p.category || '-' }}</span></td>
                  <td style="color:var(--text-muted);white-space:nowrap">{{ p.deleted_at || '-' }}</td>
                  <td style="white-space:nowrap">
                    <button class="btn btn-sm" style="background:var(--success);color:#fff;border:none;padding:4px 10px;border-radius:4px;cursor:pointer" @click="restore(p.id)">↩️ 恢复</button>
                    <button class="btn btn-sm" style="background:var(--danger);color:#fff;border:none;padding:4px 10px;border-radius:4px;cursor:pointer;margin-left:4px" @click="purge(p.id, p.product_name)">☠️ 彻底删除</button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <div v-else style="color:var(--text-muted);text-align:center;padding:40px">回收站为空</div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-default" @click="showTrash=false">关闭</button>
        </div>
      </div>
    </div>

    <!-- ====== 模态框 ====== -->
    <div class="modal-overlay" v-if="showModal">
      <div class="modal" style="max-width:800px;max-height:90vh;overflow-y:auto">
        <div class="modal-header">
          <h3>{{ modalEdit ? '✏️ 编辑产品' : '➕ 新建产品' }}</h3>
          <span class="modal-close" @click="showModal=false">&times;</span>
        </div>
        <div class="modal-body">
          <div class="form-row">
            <div class="form-col">
              <div class="form-group"><label>产品名称 <span style="color:var(--danger)">*</span></label><input class="form-input" v-model="form.product_name" placeholder="例：外壳"></div>
            </div>
            <div class="form-col">
              <div class="form-group">
                <label>产品分类</label>
                <div style="display:flex;gap:var(--space-2)">
                  <label v-for="c in categories" :key="c" style="cursor:pointer;display:flex;align-items:center;gap:var(--space-1)">
                    <input type="radio" :value="c" v-model="form.category">{{ c }}
                  </label>
                </div>
              </div>
            </div>
          </div>
          <div class="form-row">
            <div class="form-col">
              <div class="form-group"><label>型号 <span style="color:var(--danger)">*</span></label><input class="form-input" v-model="form.model" placeholder="例：SB81" @input="updateProductCode"></div>
            </div>
            <div class="form-col">
              <div class="form-group"><label>产品编码</label><input class="form-input" v-model="form.product_code" placeholder="自动生成" readonly style="background:var(--bg-hover);color:var(--text-placeholder)"></div>
            </div>
          </div>

          <!-- ===== 结构件特有字段 ===== -->
          <template v-if="form.category === '结构件'">
            <div class="form-row">
              <div class="form-col">
                <div class="form-group">
                  <label>形状/规格 <span style="color:var(--danger)">*</span></label>
                  <select class="form-input" v-model="form.spec" @change="updateProductCode">
                    <option value="">请选择规格</option>
                    <option v-for="s in specOptions" :key="s" :value="s">{{ s }}</option>
                  </select>
                </div>
              </div>
              <div class="form-col">
                <div class="form-group"><label>板厚 (mm)</label><input class="form-input" type="text" v-model="form.plate_thickness" placeholder="例：18" @input="updateProductCode"></div>
              </div>
            </div>
            <div class="form-row">
              <div class="form-col">
                <div class="form-group"><label>上口尺寸 (mm)</label><input class="form-input" type="text" v-model="form.upper_opening" placeholder="例：360" @input="updateProductCode"></div>
              </div>
              <div class="form-col">
                <div class="form-group"><label>下口尺寸 (mm)</label><input class="form-input" type="text" v-model="form.lower_opening" placeholder="例：340" @input="updateProductCode"></div>
              </div>
            </div>
            <div class="form-row">
              <div class="form-col">
                <div class="form-group"><label>派生类型</label><input class="form-input" v-model="form.style" placeholder="例：经济自用"></div>
              </div>
              <div class="form-col"></div>
            </div>
            <div class="form-row">
              <div class="form-col">
                <div class="form-group"><label>单件重量 (kg)</label><input class="form-input" type="number" step="0.01" v-model="form.weight" placeholder="如：5.2"></div>
              </div>
              <div class="form-col">
                <div class="form-group">
                  <label>价格 (元)</label>
                  <div style="display:flex;align-items:center;gap:var(--space-1)">
                    <span style="font-size:var(--text-base);color:var(--danger-dark);font-weight:700">¥</span>
                    <input class="form-input" type="number" step="0.01" min="0" v-model="form.price" placeholder="0.00" style="flex:1;font-size:var(--text-lg);font-weight:600;color:var(--danger-dark)">
                  </div>
                </div>
              </div>
            </div>
          </template>

          <!-- ===== 机加工核心字段 ===== -->
          <template v-if="form.category === '机加工'">
            <div class="form-row">
              <div class="form-col">
                <div class="form-group">
                  <label>形状/规格 <span style="color:var(--danger);font-weight:normal">*</span></label>
                  <select class="form-input" v-model="form.spec">
                    <option value="">请选择规格</option>
                    <option v-for="s in specOptions" :key="s" :value="s">{{ s }}</option>
                  </select>
                </div>
              </div>
              <div class="form-col">
                <div class="form-group"><label>板厚 (mm)</label><input class="form-input" type="text" v-model="form.plate_thickness" placeholder="如：10" @input="updateProductCode"></div>
              </div>
            </div>
            <div class="form-row">
              <div class="form-col">
                <div class="form-group"><label>派生类型</label><input class="form-input" v-model="form.style" placeholder="例：经济自用"></div>
              </div>
              <div class="form-col"></div>
            </div>
            <div class="form-row">
              <div class="form-col">
                <div class="form-group"><label>单件重量 (kg)</label><input class="form-input" type="number" step="0.01" v-model="form.weight" placeholder="0"></div>
              </div>
              <div class="form-col">
                <div class="form-group">
                  <label>价格 (元)</label>
                  <div style="display:flex;align-items:center;gap:var(--space-1)">
                    <span style="font-size:var(--text-base);color:var(--danger-dark);font-weight:700">¥</span>
                    <input class="form-input" type="number" step="0.01" min="0" v-model="form.price" placeholder="0.00" style="flex:1;font-size:var(--text-lg);font-weight:600;color:var(--danger-dark)">
                  </div>
                </div>
              </div>
            </div>
          </template>

          <div class="form-group"><label>描述</label><textarea class="form-input" v-model="form.description" rows="2" placeholder="产品描述或备注"></textarea></div>
          <div v-if="modalEdit" class="form-group" style="border-top:1px solid var(--border-light);padding-top:12px;margin-top:8px">
            <label style="font-weight:600">物料配方（BOM）- 创建订单时自动带入</label>
            <div v-if="productBom.length" style="margin-bottom:8px">
              <div v-for="bom in productBom" :key="bom.id" style="display:flex;align-items:center;gap:6px;padding:4px 0;font-size:13px">
                <span style="flex:1">{{ bom.material_name }} {{ bom.material_spec || '' }}</span>
                <span style="color:var(--text-muted);white-space:nowrap">x{{ bom.quantity_per_unit }}KG</span>
                <span v-if="bom.process_name" style="color:var(--primary);white-space:nowrap">@{{ bom.process_name }}</span>
                <button @click="removeBomItem(bom.id)" style="border:none;background:none;color:var(--danger);cursor:pointer;font-size:16px">&times;</button>
              </div>
            </div>
            <div style="display:flex;gap:6px;align-items:center">
              <select v-model="bomForm.material_id" style="flex:1;padding:4px;border:1px solid var(--border-light);border-radius:4px;font-size:13px">
                <option value="">- 选择物料 -</option>
                <option v-for="m in materialOptions" :key="m.id" :value="m.id">{{ m.name }} {{ m.spec||'' }} [{{ m.material_type||'' }}]</option>
              </select>
              <input v-model="bomForm.quantity" type="number" step="0.1" min="0.1" placeholder="用量(KG)" style="width:70px;padding:4px;border:1px solid var(--border-light);border-radius:4px;font-size:13px">
              <button @click="addBomItem" class="btn btn-sm" style="background:var(--primary);color:#fff;border:none;padding:4px 8px;border-radius:4px;cursor:pointer;white-space:nowrap">+ 添加</button>
            </div>
          </div>

          <div v-if="modalEdit" class="form-group">
            <label>附件 <span style="color:var(--text-muted);font-weight:normal">(图片/图纸/文档)</span></label>
            <div class="attachment-upload" style="margin-bottom:10px">
              <input type="file" ref="attachmentInput" id="product-attachment-input" style="display:none" accept="image/*,.pdf,.dwg,.dxf,.doc,.docx,.xls,.xlsx,.zip,.rar,.step,.stp,.igs,.iges" multiple @change="handleAttachmentUpload">
              <button type="button" class="btn btn-sm btn-default" @click="triggerAttachmentInput">+ 上传附件</button>
              <span style="color:var(--text-muted);font-size:var(--text-xs-alt);margin-left:8px">支持图片/PDF/CAD/Office，≤10MB</span>
            </div>
            <div v-if="productAttachments.length" style="display:flex;flex-wrap:wrap;gap:var(--space-3)">
              <div v-for="att in productAttachments" :key="att.id"
                style="display:flex;flex-direction:column;align-items:center;width:100px;padding:6px;background:var(--bg-table-header);border:1px solid var(--border-light);border-radius:var(--radius-md);text-align:center;cursor:pointer"
                @click="openAttachment(att)">
                <div v-if="att.file_type && att.file_type.includes('image')" style="width:72px;height:72px;border-radius:var(--radius-sm);overflow:hidden;margin-bottom:var(--space-1)">
                  <img :src="'/api/product-attachments/' + att.id + '/thumbnail?token=' + (auth.token || '')" style="width:100%;height:100%;object-fit:cover">
                </div>
                <div v-else style="font-size:32px;margin-bottom:var(--space-1);line-height:1">{{ getAttachmentIcon(att.file_type) }}</div>
                <div style="font-size:var(--text-2xs);color:var(--text-secondary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:88px" :title="att.file_name">{{ att.file_name }}</div>
                <div style="font-size:9px;color:var(--text-placeholder)">{{ formatFileSize(att.file_size) }}</div>
                <div style="display:flex;gap:var(--space-1);margin-top:4px" @click.stop>
                  <button class="attachment-delete" @click="deleteProductAttachment(att.id)" title="删除" style="font-size:var(--text-xs-alt);padding:var(--space-1) 6px;cursor:pointer;border:none;background:var(--danger-light);color:var(--danger);border-radius:var(--radius-sm)">🗑️</button>
                </div>
              </div>
            </div>
            <div v-else style="color:var(--text-muted);font-size:var(--text-xs)">暂无附件</div>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-default" @click="showModal=false">取消</button>
          <button class="btn btn-primary" @click="save">保存</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { useProduct } from '@/composables/useProduct.js'

export default {
  setup() {
    return useProduct()
  }
}
</script>
