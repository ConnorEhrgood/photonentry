/** The shapes the PhotonEntry API returns (api/app/routes/*). Only what the web app reads is typed. */

export interface TenantAccess {
  id: string
  name: string
  /** Its address in every Photon app, /org/<slug>/ (from the directory; empty until the directory has sent it: the id stands in). */
  slug: string
  former_slugs: string[]
  status: 'active' | 'suspended'
  partner_id: string | null
  role: 'owner' | 'admin' | 'operator' | 'viewer'
  scope: { all: true } | { sites: string[] }
  source: 'direct' | 'partner'
  expires_at: string | null
  capabilities: string[]
}

export interface Me {
  id: string
  name: string
  email: string
  is_platform_admin: boolean
  tenants: TenantAccess[]
}

export interface Site {
  id: string
  slug: string
  name: string
  address: string
  timezone: string
}

export interface InventoryDoor { token: string; name: string; access_points: string[] }

export interface Controller {
  id: string
  site_id: string
  name: string
  state: 'claimed' | 'disabled'
  device: { model?: string; serial?: string; firmware?: string; app_version?: string }
  inventory: { doors: InventoryDoor[] } | null
  settings: { latest: number; applied: number; error: string; current: boolean }
  last_seen: string | null
  health: { uptime_s?: number; queued_events?: number; clock?: string }
}

export interface Door {
  id: string
  name: string
  controller_id: string
  controller_door: string
  access_time_s: number
  open_too_long_s: number
  pre_alarm_s: number
  unlock_schedule_id: string | null
}

export interface Window { days: string[]; start: string; end: string }
export interface Schedule { id: string; name: string; windows: Window[]; on_holidays: 'off' | 'normal' }
export interface Rule { doors: string[]; schedule_id: string | null }
export interface Group { id: string; name: string; rules: Rule[] }
export interface Holiday { day: string; name: string }

export interface Cardholder {
  id: string
  name: string
  ref: string | null
  email: string
  person_id: string | null
  suspended: boolean
  valid_from: string | null
  valid_to: string | null
  groups: string[]
}

export interface Credential {
  id: string
  kind: 'card' | 'pin'
  card_format: 'h10301' | 'w34' | 'raw' | null
  card_facility: number | null
  hint: string
  enabled: boolean
  valid_from: string | null
  valid_to: string | null
}

export interface DoorEvent {
  controller_id: string
  seq: number
  occurred_at: string
  received_at: string
  topic: string
  door_id: string | null
  door: string | null
  cardholder_id: string | null
  cardholder: string | null
  /** The API's own words and weight for the event (app/events.py); the page words the controller's topics itself and uses these for the rest. */
  label?: string
  severity?: 'info' | 'warning' | 'critical'
  /** For "Opened from the intercom": who answered the call, from PhotonVox ("Ann Lee (101)"). */
  answered_by?: string | null
  reason: string | null
  state: string | null
}

export interface TemplateSlot { key: string; name: string; hint: string; required: boolean }
export interface SiteTemplate {
  key: string
  name: string
  description: string
  note: string
  holidays: string | null
  options: { key: string; label: string; default: boolean }[]
  slots: TemplateSlot[]
  schedules: { key: string; name: string; windows: Window[]; on_holidays: string }[]
  groups: { key: string; name: string; description: string }[]
}

export interface Applied {
  template: string
  doors: Record<string, string>
  schedules: Record<string, string>
  groups: Record<string, string>
  holidays_added: number
}

export interface Published { controllers: { controller_id: string; version: number; changed: boolean }[] }

export interface Member {
  person_id: string
  name: string
  email: string
  role: string
  scope: { all: true } | { sites: string[] }
  source: string
  pending: boolean
}

/** An Akuvox intercom at a door (BUILD-GUIDE §5). Its secrets are only in the audited setup view (IntercomSetup). */
export interface Intercom {
  id: string
  name: string
  door_id: string
  door: string
  model: string
  mac: string
  relay_address: string
  relay_target: string
  sip_server: string
  sip_port: number
  sip_transport: 'udp' | 'tcp' | 'tls'
  sip_user: string
  sip_password_set: boolean
  /** Its door station in PhotonVox: the SIP account above is that station's, kept current by PhotonEntry. */
  vox_station_id: string
  sip_synced_at: string | null
  last_fetch_at: string | null
  last_fetch_ip: string
}

export interface IntercomSetup {
  provision_url: string
  unlock_code: string
  admin_user: string
  admin_password: string
}

/** A PhotonVox door station, to choose for an intercom (never its SIP password). */
export interface VoxStation {
  id: string
  name: string
  site_id: string | null
  extension: string
}
