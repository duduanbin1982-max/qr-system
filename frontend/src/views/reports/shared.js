import { ref } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'
import { statusLabel, buildParams, exportCSV, createLoader, createExporter } from '@/lib/report-utils.js'

export { statusLabel, buildParams, exportCSV, createLoader, createExporter }

export const TABS = [
  { k: 'dashboard', l: '📊 综合看板' },
  { k: 'trend',     l: '📈 产量趋势' },
  { k: 'quality',   l: '🔍 品质分析' },
  { k: 'rework',    l: '🔧 返工分析' },
  { k: 'worker',    l: '👷 工人效率' },
  { k: 'order',     l: '📋 订单分析' },
  { k: 'model',     l: '📐 型号分布' },
  { k: 'matrix',    l: '🏷️ 产品工序矩阵' },
];
