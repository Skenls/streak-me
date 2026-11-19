import { tg } from './telegram'

export function startLiveUpdates(snapshot: () => string | null, refresh: () => void) {
  let socket: WebSocket | undefined
  let reconnectTimer: number | undefined
  let fallbackTimer: number | undefined
  let handshakeTimer: number | undefined
  let backoff = 2_000
  let nativeActive = tg?.isActive !== false
  let ready = false
  let expired = false

  const visible = () => nativeActive && document.visibilityState === 'visible' && navigator.onLine && !expired

  function fallback() {
    if (fallbackTimer !== undefined || ready || !visible()) return
    fallbackTimer = window.setTimeout(() => {
      fallbackTimer = undefined
      if (!ready && visible()) {
        refresh()
        fallback()
      }
    }, 60_000)
  }

  function connect(delay: number) {
    if (socket || reconnectTimer !== undefined || !visible() || typeof WebSocket !== 'function') return
    reconnectTimer = window.setTimeout(() => {
      reconnectTimer = undefined
      if (!visible()) return
      const address = new URL('/api/live', location.href)
      address.protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
      const attempt = new WebSocket(address)
      socket = attempt
      handshakeTimer = window.setTimeout(() => attempt.close(), 8_000)
      attempt.onopen = () => {
        if (socket === attempt) attempt.send(JSON.stringify({ proof: tg?.initData, snapshot: snapshot() }))
      }
      attempt.onmessage = ({ data }) => {
        if (socket !== attempt || !visible()) return
        if (data === 'ready') {
          ready = true
          backoff = 2_000
          clearTimeout(handshakeTimer)
          clearTimeout(fallbackTimer)
          fallbackTimer = undefined
        } else if (data === 'refresh') {
          refresh()
        }
      }
      attempt.onclose = ({ code }) => {
        if (socket !== attempt) return
        socket = undefined
        ready = false
        clearTimeout(handshakeTimer)
        if (code === 4401) {
          expired = true
          clearTimeout(fallbackTimer)
          refresh()
          return
        }
        fallback()
        connect(backoff)
        backoff = Math.min(backoff * 2, 60_000)
      }
    }, delay)
  }

  function disconnect() {
    clearTimeout(reconnectTimer)
    clearTimeout(handshakeTimer)
    clearTimeout(fallbackTimer)
    reconnectTimer = undefined
    fallbackTimer = undefined
    ready = false
    const previous = socket
    socket = undefined
    previous?.close()
  }

  function sync() {
    if (!visible()) {
      disconnect()
      return
    }
    fallback()
    connect(250)
  }

  function activated() {
    nativeActive = true
    sync()
  }

  function deactivated() {
    nativeActive = false
    disconnect()
  }

  document.addEventListener('visibilitychange', sync)
  window.addEventListener('pagehide', disconnect)
  window.addEventListener('pageshow', sync)
  window.addEventListener('online', sync)
  window.addEventListener('offline', sync)
  tg?.onEvent('activated', activated)
  tg?.onEvent('deactivated', deactivated)
  sync()

  return () => {
    disconnect()
    document.removeEventListener('visibilitychange', sync)
    window.removeEventListener('pagehide', disconnect)
    window.removeEventListener('pageshow', sync)
    window.removeEventListener('online', sync)
    window.removeEventListener('offline', sync)
    tg?.offEvent('activated', activated)
    tg?.offEvent('deactivated', deactivated)
  }
}
