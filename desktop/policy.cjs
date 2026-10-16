'use strict'

const externalHosts = new Set([
  'kalshi.com', 'www.kalshi.com', 'api.elections.kalshi.com', 'api.kalshi.com',
  'github.com', 'raw.githubusercontent.com', 'nflverse.nflverse.com',
  'www.nfl.com', 'www.sharpfootballanalysis.com',
])

function safeExternal(url) {
  try {
    const parsed = new URL(url)
    return parsed.protocol === 'https:' && !parsed.username && !parsed.password &&
      (!parsed.port || parsed.port === '443') && externalHosts.has(parsed.hostname)
  } catch { return false }
}

function localRequest(url, origin) {
  try { return new URL(url).origin === origin } catch { return false }
}

function backendPort(line) {
  try {
    const value = JSON.parse(line)
    return value.type === 'deck-backend' && Number.isInteger(value.port) && value.port > 0 && value.port < 65536
      ? value.port : null
  } catch { return null }
}

module.exports = { safeExternal, localRequest, backendPort }
