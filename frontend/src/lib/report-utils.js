import { ref } from 'vue'
import { showToast } from '@/lib/store.js'

export function statusLabel(s, ctx) {
  const orderMap = { pending: "待生产", producing: "生产中", completed: "已完成", paused: "已暂停", cancelled: "已取消" }
  const shipMap = { pending: "待发货", completed: "已完成", shipped: "已发货", partial: "部分发货" }
  const map = ctx === 'shipment' ? shipMap : orderMap
  return map[s] || s
}

export function buildParams(start, end, filterCode) {
  const p = { start: start, end: end }
  if (filterCode) p.product_code = filterCode
  return p
}

export function exportCSV(data, filename) {
  const BOM = "﻿"
  const csv = BOM + data.map(row => row.map(c => {
    const s = String(c == null ? "" : c)
    return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s
  }).join(",")).join("\n")
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" })
  const url = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = url; a.download = filename + ".csv"
  a.click(); URL.revokeObjectURL(url)
}

export function createLoader(loading, updateTime, fetchFn) {
  return async function() {
    loading.value = true
    try {
      await fetchFn()
      updateTime.value = new Date().toLocaleString("zh-CN")
    } catch (e) { showToast(e.message, "error") }
    finally { loading.value = false }
  }
}

export function createExporter(dataRef, headers, rowMapper, filePrefix) {
  return function() {
    const arr = dataRef.value
    if (!arr || !arr.length) { showToast("没有数据可导出", "warning"); return }
    const data = [headers]
    arr.forEach((item, i) => data.push(rowMapper(item, i)))
    exportCSV(data, filePrefix + "_" + new Date().toISOString().slice(0, 10))
  }
}
