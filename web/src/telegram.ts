type Insets = { top: number; right: number; bottom: number; left: number }
type TelegramEvent = 'safeAreaChanged' | 'contentSafeAreaChanged' | 'fullscreenChanged' | 'activated'

interface TelegramApp {
  initData: string
  isFullscreen?: boolean
  safeAreaInset?: Insets
  contentSafeAreaInset?: Insets
  ready(): void
  expand(): void
  isVersionAtLeast(version: string): boolean
  setHeaderColor?(color: string): void
  setBackgroundColor?(color: string): void
  disableVerticalSwipes?(): void
  requestFullscreen?(): void
  exitFullscreen?(): void
  onEvent(event: TelegramEvent, callback: () => void): void
  offEvent(event: TelegramEvent, callback: () => void): void
  openTelegramLink(url: string): void
  HapticFeedback?: { impactOccurred(style: 'light'): void }
  BackButton?: {
    show(): void
    hide(): void
    onClick(callback: () => void): void
    offClick(callback: () => void): void
  }
}

declare global {
  interface Window {
    Telegram?: { WebApp?: TelegramApp }
  }
}

export const tg = window.Telegram?.WebApp
export const inTelegram = Boolean(tg?.initData)

export function initTelegram() {
  if (!tg || !inTelegram) return () => {}
  const safeArea = () => {
    for (const side of ['top', 'right', 'bottom', 'left'] as const) {
      const inset = (tg.safeAreaInset?.[side] ?? 0) + (tg.contentSafeAreaInset?.[side] ?? 0)
      document.documentElement.style.setProperty(`--tg-inset-${side}`, `${inset}px`)
    }
  }
  const events = ['safeAreaChanged', 'contentSafeAreaChanged', 'fullscreenChanged'] as const
  for (const event of events) tg.onEvent(event, safeArea)
  if (tg.isVersionAtLeast('6.9')) {
    tg.setHeaderColor?.('#fff6ee')
    tg.setBackgroundColor?.('#fff6ee')
  }
  if (tg.isVersionAtLeast('7.7')) tg.disableVerticalSwipes?.()
  safeArea()
  tg.expand()
  tg.ready()
  return () => {
    for (const event of events) tg.offEvent(event, safeArea)
  }
}

export function haptic() {
  if (inTelegram && tg?.isVersionAtLeast('6.1')) {
    tg.HapticFeedback?.impactOccurred('light')
  } else {
    navigator.vibrate?.(12)
  }
}

export async function api<T>(path: string, method = 'GET'): Promise<T> {
  const response = await fetch(`/api/${path}`, {
    method,
    headers: { Authorization: `tma ${tg?.initData ?? ''}` },
  })
  if (response.status === 401) throw new Error('Открой StreakMe заново из Telegram.')
  if (!response.ok) throw new Error('Связь с сервером прервалась. Попробуй ещё раз.')
  return response.json()
}
