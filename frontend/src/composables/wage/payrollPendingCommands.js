const pendingCommandsByStorageKey = new Map()
const memoryOnlyStorageKeys = new Set()

export function commandKey(action) {
  return `${action}:${Date.now()}:${Math.random().toString(16).slice(2)}`
}

export function normalizeCommandReason(value) {
  return String(value ?? '').trim().replace(/\s+/gu, ' ')
}

function inMemoryPendingCommands(storageKey) {
  if (!pendingCommandsByStorageKey.has(storageKey)) {
    pendingCommandsByStorageKey.set(storageKey, new Map())
  }
  return pendingCommandsByStorageKey.get(storageKey)
}

function readPendingCommands(storageKey) {
  const fallback = inMemoryPendingCommands(storageKey)
  let serialized
  try {
    serialized = sessionStorage.getItem(storageKey)
  } catch (_) {
    memoryOnlyStorageKeys.add(storageKey)
    return fallback
  }
  if (!serialized) {
    if (memoryOnlyStorageKeys.has(storageKey)) return fallback
    const empty = new Map()
    pendingCommandsByStorageKey.set(storageKey, empty)
    return empty
  }
  try {
    const entries = JSON.parse(serialized)
    const commands = new Map(
      Array.isArray(entries)
        ? entries.filter(entry => (
          Array.isArray(entry)
          && typeof entry[0] === 'string'
          && typeof entry[1] === 'string'
        ))
        : []
    )
    pendingCommandsByStorageKey.set(storageKey, commands)
    memoryOnlyStorageKeys.delete(storageKey)
    return commands
  } catch (_) {
    const empty = new Map()
    pendingCommandsByStorageKey.set(storageKey, empty)
    memoryOnlyStorageKeys.delete(storageKey)
    return empty
  }
}

function persistPendingCommands(storageKey, commands) {
  try {
    if (commands.size) {
      sessionStorage.setItem(storageKey, JSON.stringify([...commands]))
    } else {
      sessionStorage.removeItem(storageKey)
    }
    memoryOnlyStorageKeys.delete(storageKey)
  } catch (_) {
    memoryOnlyStorageKeys.add(storageKey)
  }
}

export function pendingCommandKey(storageKey, action, signature) {
  const commands = readPendingCommands(storageKey)
  if (commands.has(signature)) return commands.get(signature)
  const key = commandKey(action)
  commands.set(signature, key)
  persistPendingCommands(storageKey, commands)
  return key
}

export function clearPendingCommand(storageKey, signature) {
  const commands = readPendingCommands(storageKey)
  if (!commands.delete(signature)) return
  persistPendingCommands(storageKey, commands)
}
