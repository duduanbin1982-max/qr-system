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
export const TABS_WITH_PRODUCT = ["worker", "product", "shipment", "material"]

export { statusLabel, buildParams, exportCSV, createLoader, createExporter } from "@/lib/report-utils.js"
