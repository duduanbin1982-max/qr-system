export const TABS = [
  { k: "daily",    l: "📊 日报表" },
  { k: "worker",   l: "👷 员工计件" },
  { k: "scrap",    l: "⚠️ 报废记录" },
  { k: "matrix",   l: "🔢 工序统计" },
  { k: "progress", l: "📈 订单进度" },
  { k: "product",  l: "🏷️ 产品统计" },
  { k: "shipment", l: "🚚 发货统计" },
  { k: "material", l: "📦 物料消耗" },
  { k: "customer", l: "🏢 客户统计" },
]

export const TABS_WITH_DATE = ["daily", "worker", "scrap", "matrix", "product", "shipment", "material", "customer"]
export const TABS_WITH_PRODUCT = ["worker", "product", "material"]

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
export { statusLabel, buildParams, createLoader, createExporter } from "@/lib/report-utils.js"
