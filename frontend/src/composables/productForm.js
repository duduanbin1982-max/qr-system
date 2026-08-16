export const PRODUCT_CATEGORIES = ['结构件', '机加工']
export const STRUCTURAL_SPECS = ['三角型', '静音型', '分体直型', '一体直型']
export const MACHINING_SPECS = ['经济型', '标准型', '定制型']

const STRING_FIELDS = [
  'product_name', 'model', 'spec', 'style', 'upper_opening', 'lower_opening',
  'plate_thickness', 'category', 'description',
]

export function createProductForm(product = {}, fallbackCategory = '结构件') {
  return {
    product_name: product.product_name || '',
    product_code: product.product_code || '',
    model: product.model || '',
    spec: product.spec || '',
    style: product.style || '',
    upper_opening: product.upper_opening || '',
    lower_opening: product.lower_opening || '',
    plate_thickness: product.plate_thickness || '',
    weight: product.weight ?? '',
    category: product.category || fallbackCategory,
    price: product.price ?? '',
    description: product.description || '',
    process_route_id: product.process_route_id ?? product.route_id ?? null,
  }
}

export function optionalNumber(value, label) {
  if (value === '' || value == null) return null
  const number = Number(value)
  if (!Number.isFinite(number) || number < 0) {
    throw new Error(`${label}必须是大于或等于0的有效数字`)
  }
  return number
}

export function normalizeProductPayload(form) {
  const payload = {}
  for (const field of STRING_FIELDS) payload[field] = String(form[field] ?? '').trim()
  payload.weight = optionalNumber(form.weight, '重量')
  payload.price = optionalNumber(form.price, '价格')
  payload.process_route_id = form.process_route_id || null
  return payload
}

export function positiveBomQuantity(value) {
  const quantity = Number(value)
  if (!Number.isFinite(quantity) || quantity <= 0) {
    throw new Error('单位用量必须是大于0的有效数字')
  }
  return quantity
}
