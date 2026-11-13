import type { DoorEvent, Window } from '../api/types'

const DAY_NAMES: Record<string, string> = { mo: 'Mon', tu: 'Tue', we: 'Wed', th: 'Thu', fr: 'Fri', sa: 'Sat', su: 'Sun' }
const ORDER = ['mo', 'tu', 'we', 'th', 'fr', 'sa', 'su']

/** "Mon–Fri", "Sat, Sun", "Every day": runs of consecutive days are joined. */
export function days(list: string[]): string {
  const sorted = ORDER.filter((d) => list.includes(d))
  if (sorted.length === 7) return 'Every day'
  const runs: string[][] = []
  for (const d of sorted) {
    const last = runs[runs.length - 1]
    if (last && ORDER.indexOf(d) === ORDER.indexOf(last[last.length - 1]) + 1) last.push(d)
    else runs.push([d])
  }
  return runs.map((r) => (r.length > 2 ? `${DAY_NAMES[r[0]]}–${DAY_NAMES[r[r.length - 1]]}` : r.map((d) => DAY_NAMES[d]).join(', '))).join(', ')
}

export function windows(ws: Window[]): string {
  return ws.map((w) => `${days(w.days)} ${w.start}–${w.end}`).join('; ')
}

const REASONS: Record<string, string> = {
  NotPermittedAtThisTime: 'outside its schedule', CredentialNotEnabled: 'credential turned off', CredentialExpired: 'credential expired',
  CredentialNotActive: 'credential not active yet', InvalidAccessProfile: 'no access group here', Unauthorized: 'no access here',
}

/** An event in a few words, and how it should look: denied and forced are warnings, the rest information. */
export function describe(e: DoorEvent): { text: string; tone: 'ok' | 'info' | 'warning' | 'error' } {
  const t = e.topic
  if (t === 'AccessControl/AccessGranted/Credential') return { text: 'Access granted', tone: 'ok' }
  if (t === 'AccessControl/AccessGranted/Anonymous') return { text: 'Exit button', tone: 'info' }
  if (t === 'AccessControl/AccessTaken/Credential') return { text: 'Door opened after access', tone: 'info' }
  if (t === 'AccessControl/AccessNotTaken/Credential') return { text: 'Access not used', tone: 'info' }
  if (t === 'AccessControl/Denied/Credential') return { text: `Denied: ${REASONS[e.reason ?? ''] ?? (e.reason || 'refused')}`, tone: 'warning' }
  if (t.startsWith('AccessControl/Denied/CredentialNotFound')) return { text: 'Denied: unknown card or PIN', tone: 'warning' }
  if (t === 'Door/State/DoorAlarm') {
    if (e.state === 'DoorForcedOpen') return { text: 'Door forced open', tone: 'error' }
    if (e.state === 'DoorOpenTooLong') return { text: 'Door held open', tone: 'error' }
    return { text: 'Door alarm cleared', tone: 'ok' }
  }
  if (t === 'Door/State/DoorPhysicalState') return { text: e.state === 'Open' ? 'Door opened' : 'Door closed', tone: 'info' }
  if (t === 'Door/State/DoorMode') return { text: `Door ${({ Locked: 'locked', Unlocked: 'unlocked', Accessed: 'unlocked for access', LockedDown: 'locked down', LockedOpen: 'held open', Blocked: 'blocked' } as Record<string, string>)[e.state ?? ''] ?? (e.state ?? '').toLowerCase()}`, tone: e.state === 'LockedDown' ? 'warning' : 'info' }
  if (t === 'Door/State/DoorWarning') return { text: 'Door open too long soon', tone: 'warning' }
  return { text: t.split('/').slice(-2).join(' '), tone: 'info' }
}
