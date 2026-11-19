import { useState, type CSSProperties } from 'react'
import type { Person } from './model'
import seriychik from './assets/seriychik.webp'

export function Avatar({ person, hue }: { person: Person; hue: number }) {
  const [failedUrl, setFailedUrl] = useState<string>()
  const initials = person.name.trim().split(/\s+/).slice(0, 2)
    .map(word => Array.from(word)[0] ?? '').join('').toUpperCase()
  return <span className="avatar" style={{ '--avatar-hue': hue } as CSSProperties} aria-hidden="true">
    {initials}
    {person.photoUrl && failedUrl !== person.photoUrl && (
      <img src={person.photoUrl} alt="" draggable="false" referrerPolicy="no-referrer"
        onError={() => setFailedUrl(person.photoUrl ?? '')} />
    )}
  </span>
}

export function Flame({ mascot = false }: { mascot?: boolean }) {
  if (mascot) return <span className="mascot" aria-hidden="true">
    <img src={seriychik} width="512" height="512" alt="" draggable="false" />
  </span>

  return <span className="flame" aria-hidden="true"><span className="flame-body" /></span>
}
