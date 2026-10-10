function normalizedSnapshot(value) {
  if (Array.isArray(value)) return value.map(normalizedSnapshot)
  if (!value || typeof value !== 'object') return value
  return Object.fromEntries(
    Object.keys(value).sort().map(key => [key, normalizedSnapshot(value[key])]),
  )
}

export function createInventoryQueryCoordinator() {
  let sequence = 0

  function begin(snapshot) {
    sequence += 1
    return Object.freeze({
      sequence,
      digest: JSON.stringify(normalizedSnapshot(snapshot)),
    })
  }

  function isCurrent(request) {
    return request?.sequence === sequence
  }

  function invalidate() {
    sequence += 1
  }

  return { begin, isCurrent, invalidate }
}
