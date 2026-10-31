export function formatUnitPrice(value) {
  return `¥${(Number(value || 0) / 10000).toFixed(4)}`
}

export function formatLocalMonth(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`
}
