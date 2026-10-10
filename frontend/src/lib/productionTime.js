export const PRODUCTION_TIME_ZONE = 'Asia/Shanghai'
export const PRODUCTION_OFFSET = '+08:00'

const DATE_ONLY = /^(\d{4})-(\d{2})-(\d{2})$/
const LOCAL_DATE_TIME = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?$/
const EXPLICIT_OFFSET = /(Z|[+-]\d{2}:?\d{2})$/i

const calendarFormatter = new Intl.DateTimeFormat('en-CA', {
  timeZone: PRODUCTION_TIME_ZONE,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hourCycle: 'h23',
  weekday: 'short',
})

function pad(value) {
  return String(value).padStart(2, '0')
}

export function productionCalendarParts(value = new Date()) {
  const parsed = parseProductionTimestamp(value)
  if (!parsed) return null
  const parts = Object.fromEntries(calendarFormatter.formatToParts(parsed).map(item => [item.type, item.value]))
  const weekdays = { Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6, Sun: 7 }
  return {
    year: Number(parts.year),
    month: Number(parts.month),
    day: Number(parts.day),
    hour: Number(parts.hour),
    minute: Number(parts.minute),
    second: Number(parts.second),
    weekday: weekdays[parts.weekday],
  }
}

export function parseProductionTimestamp(value) {
  if (value instanceof Date) {
    const cloned = new Date(value.getTime())
    return Number.isNaN(cloned.getTime()) ? null : cloned
  }
  const text = String(value || '').trim()
  if (!text) return null
  let normalized = text
  if (DATE_ONLY.test(text)) normalized = `${text}T00:00:00${PRODUCTION_OFFSET}`
  else if (LOCAL_DATE_TIME.test(text) && !EXPLICIT_OFFSET.test(text)) {
    normalized = `${text.replace(' ', 'T')}${PRODUCTION_OFFSET}`
  } else {
    normalized = text.replace(' ', 'T')
  }
  const parsed = new Date(normalized)
  return Number.isNaN(parsed.getTime()) ? null : parsed
}

export function productionDate(value = new Date()) {
  const parts = productionCalendarParts(value)
  return parts ? `${parts.year}-${pad(parts.month)}-${pad(parts.day)}` : ''
}

export function productionDateTimeLocal(value = new Date()) {
  const parts = productionCalendarParts(value)
  return parts
    ? `${parts.year}-${pad(parts.month)}-${pad(parts.day)}T${pad(parts.hour)}:${pad(parts.minute)}`
    : ''
}

export function productionApiTimestamp(value) {
  const text = String(value || '').trim()
  if (!text) return ''
  const local = LOCAL_DATE_TIME.exec(text)
  if (local && !EXPLICIT_OFFSET.test(text)) {
    return `${local[1]}-${local[2]}-${local[3]}T${local[4]}:${local[5]}:${local[6] || '00'}${PRODUCTION_OFFSET}`
  }
  const parsed = parseProductionTimestamp(value)
  if (!parsed) throw new Error('生产时间格式无效')
  const parts = productionCalendarParts(parsed)
  return `${parts.year}-${pad(parts.month)}-${pad(parts.day)}T${pad(parts.hour)}:${pad(parts.minute)}:${pad(parts.second)}${PRODUCTION_OFFSET}`
}

export function productionInputDateTime(value) {
  return productionDateTimeLocal(value)
}

export function productionStartOfDay(value = new Date()) {
  const date = productionDate(value)
  return parseProductionTimestamp(date)
}

export function addProductionDays(value, days) {
  const parts = productionCalendarParts(value)
  if (!parts) return null
  const shifted = new Date(Date.UTC(parts.year, parts.month - 1, parts.day + Number(days || 0), 0, 0, 0))
  const date = `${shifted.getUTCFullYear()}-${pad(shifted.getUTCMonth() + 1)}-${pad(shifted.getUTCDate())}`
  return parseProductionTimestamp(date)
}

export function formatProductionDateTime(value) {
  const parts = productionCalendarParts(value)
  return parts
    ? `${pad(parts.month)}-${pad(parts.day)} ${pad(parts.hour)}:${pad(parts.minute)}`
    : '-'
}
