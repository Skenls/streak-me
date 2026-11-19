export interface Person {
  name: string
  photoUrl?: string | null
}

export interface Streak {
  id: number
  days: number
  confirmed: boolean
  friendConfirmed: boolean
  friend: Person & { id: number; username?: string | null }
}

export interface Dashboard {
  me: Person
  streaks: Streak[]
}

export const tiers = [
  { from: 0, name: 'Искра', hue: 32 },
  { from: 3, name: 'Тепло', hue: 45 },
  { from: 10, name: 'Пламя', hue: 20 },
  { from: 30, name: 'Зарево', hue: 350 },
  { from: 100, name: 'Неон', hue: 308 },
  { from: 200, name: 'Сверхновая', hue: 206 },
]

export function rank(days: number) {
  const firstLocked = tiers.findIndex(tier => days < tier.from)
  const index = firstLocked === -1 ? tiers.length - 1 : firstLocked - 1
  return { tier: tiers[index], next: tiers[index + 1] }
}

export function daysLabel(days: number) {
  const ones = days % 10
  const teens = days % 100 >= 11 && days % 100 <= 14
  if (ones === 1 && !teens) return 'день'
  if (ones >= 2 && ones <= 4 && !teens) return 'дня'
  return 'дней'
}

export function pairState(pair: Streak) {
  if (pair.confirmed && pair.friendConfirmed) return 'День засчитан'
  if (pair.confirmed) return 'Ждём друга'
  if (pair.friendConfirmed) return 'Друг уже отметился'
  return 'Пора отметиться'
}
