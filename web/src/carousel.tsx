import { useRef, useState, type CSSProperties, type UIEvent } from 'react'
import { daysLabel, pairState, rank, type Streak } from './model'
import { haptic } from './telegram'
import { Avatar, Flame } from './visuals'

const nativeTimeline = CSS.supports('(animation-timeline: view()) and (animation-range: entry)')

export function Carousel({ streaks, motion, onSelect }: {
  streaks: Streak[]; motion: boolean; onSelect(pair: Streak): void
}) {
  const scroller = useRef<HTMLOListElement>(null)
  const current = useRef(0)
  const [active, setActive] = useState(0)

  function update(event: UIEvent<HTMLOListElement>) {
    const list = event.currentTarget
    const [first, second] = list.children as HTMLCollectionOf<HTMLElement>
    if (!second) return
    const step = second.offsetLeft - first.offsetLeft
    if (!step) return
    const progress = Math.max(0, Math.min(list.scrollLeft / step, streaks.length - 1))
    const index = Math.round(progress)
    if (!nativeTimeline) {
      for (let n = Math.max(0, index - 2); n <= Math.min(index + 2, streaks.length - 1); n++) {
        const distance = Math.max(-1, Math.min(1, n - progress))
        const slide = list.children[n] as HTMLElement
        slide.style.setProperty('--offset', String(distance))
        slide.style.setProperty('--distance', String(Math.abs(distance)))
      }
    }
    if (index !== current.current) {
      current.current = index
      setActive(index)
      haptic()
    }
  }

  function go(index: number) {
    const list = scroller.current
    const slide = list?.children[index] as HTMLElement | undefined
    const first = list?.firstElementChild as HTMLElement | null
    if (!list || !slide || !first) return
    list.scrollTo({
      left: slide.offsetLeft - first.offsetLeft,
      behavior: motion && !matchMedia('(prefers-reduced-motion: reduce)').matches ? 'smooth' : 'instant',
    })
  }

  return <section className="carousel-wrap" aria-label="Серии с друзьями">
    <ol className="carousel" ref={scroller} onScroll={update} onKeyDown={event => {
      if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
      event.preventDefault()
      go(current.current + (event.key === 'ArrowRight' ? 1 : -1))
    }}>
      {streaks.map((pair, index) => {
        const { tier } = rank(pair.days)
        return <li className="slide" key={pair.id} data-active={active === index}
          style={{ '--hue': tier.hue, '--initial-offset': Math.sign(index) } as CSSProperties}>
          <button className="streak-card" type="button" onClick={() => onSelect(pair)}
            aria-label={`${pair.friend.name}, ${pair.days} ${daysLabel(pair.days)}, открыть серию`}>
            <span className="card-level"><span />{tier.name}</span>
            <span className="card-count"><Flame /><strong>{pair.days}</strong><small>{daysLabel(pair.days)}</small></span>
            <span className="card-scene">
              <span className="card-twinkle" aria-hidden="true">✦</span>
              <Avatar person={pair.friend} hue={tier.hue + 15} />
              <Flame mascot />
            </span>
            <span className="friend-name">{pair.friend.name}</span>
            {pair.friend.username && <span className="handle">@{pair.friend.username}</span>}
            <span className="card-status">{pairState(pair)}</span>
          </button>
        </li>
      })}
    </ol>
    {streaks.length > 1 && <div className="carousel-controls">
      <button className="icon-button" type="button" aria-label="Предыдущая серия"
        disabled={active <= 0} onClick={() => go(active - 1)}><span className="chevron left" /></button>
      <div className="dots">
        {streaks.map((pair, index) => <button key={pair.id} type="button"
          aria-label={pair.friend.name} aria-current={index === active ? 'true' : undefined}
          onClick={() => go(index)}><span /></button>)}
      </div>
      <button className="icon-button" type="button" aria-label="Следующая серия"
        disabled={active >= streaks.length - 1} onClick={() => go(active + 1)}><span className="chevron" /></button>
    </div>}
  </section>
}
