import { useCallback, useEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { Carousel } from './carousel'
import { daysLabel, pairState, rank, type Dashboard, type Person, type Streak } from './model'
import { api, haptic, initTelegram, inTelegram, tg } from './telegram'
import { Avatar, Flame } from './visuals'
import './fonts.css'
import './style.css'

function Modal({ children, onClose, className, style }: {
  children: ReactNode; onClose(): void; className: string; style?: CSSProperties
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  const close = useRef(onClose)
  useEffect(() => { close.current = onClose }, [onClose])
  useEffect(() => {
    const element = dialog.current!
    const back = () => element.close()
    element.showModal()
    const backButton = inTelegram && tg?.isVersionAtLeast('6.1') ? tg.BackButton : undefined
    backButton?.onClick(back)
    backButton?.show()
    return () => {
      backButton?.offClick(back)
      backButton?.hide()
    }
  }, [])
  return <dialog ref={dialog} className={className} style={style} aria-labelledby="dialog-title"
    onClose={() => close.current()}>
    <button type="button" className="icon-button close-button" aria-label="Закрыть"
      onClick={() => dialog.current?.close()}><span className="cross" /></button>
    {children}
  </dialog>
}

type DetailAction = 'confirm' | 'restore' | 'delete'

function Detail({ pair, me, onClose, onAction }: {
  pair: Streak; me: Person; onClose(): void; onAction(action: DetailAction): Promise<void>
}) {
  const { tier, next } = rank(pair.days)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [celebrate, setCelebrate] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const lost = pair.status === 'lost'

  async function submit(action: DetailAction) {
    setError('')
    setBusy(true)
    try {
      await onAction(action)
      if (action === 'confirm') setCelebrate(true)
      haptic()
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Попробуй ещё раз.')
    } finally {
      setBusy(false)
    }
  }

  const hue = pair.status === 'frozen' ? 203 : lost ? 220 : tier.hue
  return <Modal className="detail" onClose={onClose} style={{ '--hue': hue } as CSSProperties}>
    <div className="detail-shell">
      <button className="icon-button delete-button" type="button" aria-label="Удалить огонёк"
        aria-expanded={deleting} disabled={busy} onClick={() => { setError(''); setDeleting(!deleting) }}>
        <span className="trash" aria-hidden="true" />
      </button>
      <header className="detail-header">
        <span className="card-level"><span />{lost ? 'Огонёк погас' : tier.name}</span>
        <h2 id="dialog-title">{pair.friend.name}</h2>
        {pair.friend.username && <p>@{pair.friend.username}</p>}
      </header>
      {deleting && <section className="delete-confirm" aria-label="Подтверждение удаления огонька">
        <p>Удалить огонёк у вас обоих? Чтобы начать новую серию, понадобится приглашение.</p>
        <div>
          <button className="secondary" type="button" disabled={busy} onClick={() => setDeleting(false)}>Отмена</button>
          <button className="danger" type="button" disabled={busy} onClick={() => void submit('delete')}>Удалить у обоих</button>
        </div>
        {error && <p className="error" role="alert">{error}</p>}
      </section>}
      <div className="mascot-stage" data-celebrate={celebrate && pair.status === 'active'}>
        {!lost && <>
          <span className="orbit" aria-hidden="true" />
          <span className="spark one" aria-hidden="true">✧</span>
          <span className="spark two" aria-hidden="true">✦</span>
          <span className="spark three" aria-hidden="true">✦</span>
        </>}
        <Flame mascot status={pair.status} />
      </div>
      <div className="detail-score"><strong>{pair.days}</strong><span>{daysLabel(pair.days)} подряд</span></div>
      {!lost && next && <div className="milestone">
        <div><span>До ступени «{next.name}»</span><b>{next.from - pair.days} {daysLabel(next.from - pair.days)}</b></div>
        <progress value={pair.days - tier.from} max={next.from - tier.from} aria-label="Прогресс до следующей ступени" />
      </div>}
      {lost ? <section className="today restore-panel">
        <h3>Серия прервалась</h3>
        <p>В этом месяце осталось {pair.restoresLeft} из 5 восстановлений на двоих.</p>
        <button className="primary" type="button" disabled={busy || !pair.restoresLeft}
          onClick={() => void submit('restore')}>Восстановить огонёк</button>
        <p className="rule">Счёт вернётся. Чтобы засчитать сегодня, отметьтесь оба.</p>
        {!deleting && error && <p className="error" role="alert">{error}</p>}
      </section> : <section className="today">
        <header><h3>Сегодня</h3><span>{pairState(pair)}</span></header>
        <div className="participant"><Avatar person={me} hue={264} /><b>Ты</b><span>
          {pair.confirmed ? '✓ Есть отметка' : 'Без отметки'}
        </span></div>
        <div className="participant"><Avatar person={pair.friend} hue={tier.hue + 15} />
          <b>{pair.friend.name}</b><span>{pair.friendConfirmed ? '✓ Есть отметка' : 'Без отметки'}</span>
        </div>
        <button className="primary" type="button" onClick={() => void submit('confirm')} disabled={busy || pair.confirmed}>
          {pair.confirmed ? 'Ты уже отметился' : busy ? 'Сохраняем…' : 'Отметиться сегодня'}
        </button>
        <p className="rule">День засчитывается, когда отмечаются оба. Новый день начинается в 00:00 UTC.</p>
        {!deleting && error && <p className="error" role="alert">{error}</p>}
      </section>}
    </div>
  </Modal>
}

function Invite({ onClose }: { onClose(): void }) {
  const [url, setUrl] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)

  async function prepare() {
    setBusy(true)
    setNotice('')
    try {
      const result = await api<{ url: string }>('invite', 'POST')
      setUrl(result.url)
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Попробуй ещё раз.')
    } finally {
      setBusy(false)
    }
  }

  function share() {
    const link = `https://t.me/share/url?url=${encodeURIComponent(url)}&text=${encodeURIComponent('Давай зажжём общий огонёк в StreakMe! 🔥')}`
    tg?.openTelegramLink(link)
  }

  return <Modal className="invite-modal" onClose={onClose}>
    <div className="invite-art"><Flame /></div>
    <h2 id="dialog-title">Пригласить друга</h2>
    <p>По твоей ссылке друзья могут зажечь с тобой огонёк. Чтобы заменить её, отправь боту /reset.</p>
    {url
      ? <><button type="button" className="primary" onClick={share}>Поделиться в Telegram</button>
        <input className="invite-link" readOnly aria-label="Ссылка-приглашение" value={url}
          onFocus={event => event.currentTarget.select()} /></>
      : <button type="button" className="primary" disabled={busy} onClick={prepare}>
        {busy ? 'Загружаем…' : 'Показать мою ссылку'}
      </button>}
    {notice && <p className="error" role="alert">{notice}</p>}
  </Modal>
}

function App() {
  const [data, setData] = useState<Dashboard | null>(null)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState<number>()
  const [inviting, setInviting] = useState(false)
  const revision = useRef(0)
  const refreshing = useRef(false)
  const streaks = data?.streaks ?? []
  const detail = streaks.find(pair => pair.id === selected)

  const refresh = useCallback(async () => {
    if (refreshing.current) return
    refreshing.current = true
    const request = ++revision.current
    try {
      const dashboard = await api<Dashboard>('streaks')
      if (request === revision.current) {
        setData(dashboard)
        setError('')
      }
    } catch (error) {
      if (request === revision.current) {
        setError(error instanceof Error ? error.message : 'Не удалось загрузить огоньки.')
      }
    } finally {
      refreshing.current = false
    }
  }, [])

  useEffect(() => {
    const cleanup = initTelegram()
    function refreshVisible() {
      if (document.visibilityState === 'visible') void refresh()
    }
    void refresh()
    const timer = window.setInterval(refreshVisible, 30_000)
    document.addEventListener('visibilitychange', refreshVisible)
    tg?.onEvent('activated', refreshVisible)
    return () => {
      clearInterval(timer)
      document.removeEventListener('visibilitychange', refreshVisible)
      tg?.offEvent('activated', refreshVisible)
      cleanup()
    }
  }, [refresh])

  async function updatePair(pair: Streak, action: DetailAction) {
    const path = `streaks/${pair.id}`
    if (action === 'delete') {
      await api<void>(path, 'DELETE')
      revision.current++
      setSelected(undefined)
      setData(previous => previous && {
        ...previous, streaks: previous.streaks.filter(value => value.id !== pair.id),
      })
      return
    }
    const updated = await api<Streak>(`${path}/${action}`, 'POST')
    revision.current++
    setError('')
    setData(previous => previous && {
      ...previous, streaks: previous.streaks.map(value => value.id === updated.id ? updated : value),
    })
  }

  return <main className="app">
    <header className="topbar">
      <div className="brand"><span className="brand-mark"><Flame /></span>streak<span>me</span></div>
    </header>
    <div className="page-heading">
      <h1>Твои огоньки<span>.</span></h1>
      <p>Перелистывай серии и отмечайся вместе с друзьями.</p>
    </div>
    {error && <div className="load-error"><p role="alert">{error}</p>
      <button type="button" className="secondary" onClick={refresh}>Повторить</button></div>}
    {data ? (streaks.length
      ? <Carousel streaks={streaks} onSelect={pair => setSelected(pair.id)} />
      : <section className="empty"><Flame mascot /><h2>Зажги первый огонёк</h2>
        <p>Пригласи друга, чтобы начать общую серию.</p></section>
    ) : !error && <p className="loading" role="status">Загружаем огоньки…</p>}
    {data && <footer className="footer">
      <button className="primary" type="button" onClick={() => setInviting(true)}><span aria-hidden="true">+</span> Пригласить друга</button>
    </footer>}
    {detail && data && <Detail key={detail.id} pair={detail} me={data.me}
      onClose={() => setSelected(undefined)} onAction={action => updatePair(detail, action)} />}
    {inviting && <Invite onClose={() => setInviting(false)} />}
  </main>
}

createRoot(document.getElementById('root')!).render(inTelegram ? <App /> :
  <main className="app launch">
    <section className="empty">
      <Flame mascot />
      <h1>StreakMe</h1>
      <p>Открой приложение из чата с ботом в Telegram.</p>
    </section>
  </main>,
)
