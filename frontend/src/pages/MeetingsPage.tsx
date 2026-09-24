import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Building2,
  CalendarCheck,
  CalendarClock,
  Check,
  ClipboardList,
  Clock3,
  Copy,
  ExternalLink,
  ListTodo,
  Mail,
  MessageSquare,
  Plus,
  Users,
  X,
} from 'lucide-react'
import { customerApi, meetingApi } from '../api'
import type { MeetingAvailability, MeetingInvite } from '../api/types'
import { Badge, Button, EmptyState, Field, inputCls, Panel, PanelTitle, selectCls, Spinner } from '../components/ui'

const ORIGIN = window.location.origin

const fmtDateTime = (v?: string | null) => (v ? new Date(v).toLocaleString() : '—')
const toISO = (local: string) => (local ? new Date(local).toISOString() : '')

const initials = (name: string) =>
  name
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? '')
    .join('') || '?'

function relTime(iso?: string | null): { label: string; upcoming: boolean } | null {
  if (!iso) return null
  const diffMs = new Date(iso).getTime() - Date.now()
  const abs = Math.abs(diffMs) / 60000
  const prefix = diffMs >= 0 ? 'in' : 'ago'
  if (abs < 60) return { label: `${Math.round(abs)}m ${prefix}`, upcoming: diffMs >= 0 }
  if (abs < 1440) return { label: `${Math.round(abs / 60)}h ${prefix}`, upcoming: diffMs >= 0 }
  return { label: `${Math.round(abs / 1440)}d ${prefix}`, upcoming: diffMs >= 0 }
}

function expiresIn(iso?: string | null): { label: string; expiresSoon: boolean } | null {
  if (!iso) return null
  const hrs = (new Date(iso).getTime() - Date.now()) / 3_600_000
  if (hrs <= 0) return { label: 'Expired', expiresSoon: true }
  const label = hrs < 24 ? `Expires in ${Math.max(1, Math.round(hrs))}h` : `Expires in ${Math.max(1, Math.round(hrs / 24))}d`
  return { label, expiresSoon: hrs <= 24 }
}

const statusMeta = (s: string) => {
  switch (s) {
    case 'selected':
    case 'submitted-form':
      return { label: 'Responded', tone: 'green' as const }
    case 'expired':
      return { label: 'Expired', tone: 'coral' as const }
    case 'sent':
      return { label: 'Awaiting reply', tone: 'teal' as const }
    default:
      return { label: s, tone: 'navy' as const }
  }
}

async function copy(text: string) {
  await navigator.clipboard.writeText(text)
  window.alert('Link copied to clipboard')
}

export default function MeetingsPage() {
  const [tab, setTab] = useState<'invites' | 'availability'>('invites')

  const invites = useQuery({ queryKey: ['meeting-invites'], queryFn: () => meetingApi.invites() })
  const availability = useQuery({ queryKey: ['meeting-availability'], queryFn: () => meetingApi.availabilityList() })

  const invitesCount = invites.data?.length ?? 0
  const avail = availability.data ?? []
  const responded = avail.filter((a) => a.status === 'selected' || a.status === 'submitted-form').length
  const pending = avail.filter((a) => a.status === 'sent' && (!a.expires_at || new Date(a.expires_at) > new Date())).length
  const responseRate = avail.length ? Math.round((responded / avail.length) * 100) : 0

  const TABS = [
    { key: 'invites', label: 'Invites', icon: Mail, count: invitesCount },
    { key: 'availability', label: 'Availability', icon: CalendarClock, count: avail.length },
  ] as const

  return (
    <div className="space-y-6">
      {/* ── Hero ─────────────────────────────────────────────── */}
      <section className="ambiflow-hero relative overflow-hidden rounded-3xl border border-brand-teal/20 p-6 shadow-xl shadow-navy-900/10 sm:p-8">
        <div className="dot-grid" />
        <div className="glow-orb h-44 w-44 animate-float bg-brand-cyan/30" style={{ top: '-60px', right: '8%' }} />
        <div className="glow-orb h-44 w-44 animate-float bg-brand-teal/25" style={{ bottom: '-70px', right: '35%', animationDelay: '-3s' }} />

        <div className="relative z-10 flex flex-wrap items-center justify-between gap-6">
          <div>
            <div className="flex items-center gap-2">
              <CalendarClock size={16} className="text-brand-cyan" />
              <span className="font-display text-[11px] font-bold uppercase tracking-[0.25em] text-brand-cyan">
                Ambifo CRM · Scheduling
              </span>
            </div>
            <h1 className="mt-2 font-display text-2xl font-bold text-white sm:text-3xl">Meetings</h1>
            <p className="mt-1.5 text-sm text-slate-400">
              Invite customers to meetings and let them pick times that work, right from a public link.
            </p>
          </div>

          <div className="flex items-center gap-3">
            <div className="flex flex-col items-center rounded-2xl border border-white/10 bg-white/5 px-6 py-4 backdrop-blur-sm transition-colors hover:border-brand-cyan/40">
              <span className="font-display text-2xl font-bold text-white">{invitesCount}</span>
              <span className="mt-0.5 font-display text-[10px] font-semibold uppercase tracking-widest text-brand-cyan">
                Invites
              </span>
            </div>
            <div className="hidden flex-col items-center rounded-2xl border border-amber-400/25 bg-amber-500/10 px-6 py-4 backdrop-blur-sm transition-colors hover:border-amber-400/50 sm:flex">
              <span className="font-display text-2xl font-bold text-amber-300">{pending}</span>
              <span className="mt-0.5 font-display text-[10px] font-semibold uppercase tracking-widest text-amber-400">
                Awaiting reply
              </span>
            </div>
            <div className="hidden flex-col items-center rounded-2xl border border-emerald-400/25 bg-emerald-500/10 px-6 py-4 backdrop-blur-sm transition-colors hover:border-emerald-400/50 sm:flex">
              <span className="font-display text-2xl font-bold text-emerald-300">{responseRate}%</span>
              <span className="mt-0.5 font-display text-[10px] font-semibold uppercase tracking-widest text-emerald-400">
                Response rate
              </span>
            </div>
          </div>
        </div>
      </section>

      {/* ── Tabs ─────────────────────────────────────────────── */}
      <div className="scroll-fade flex w-fit gap-1 rounded-2xl border border-slate-200 bg-white p-1 shadow-sm">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`flex items-center gap-2 rounded-xl px-4 py-2 font-display text-sm font-bold transition-all duration-300 ${
              tab === t.key ? 'bg-navy-900 text-white shadow-md' : 'text-slate-500 hover:bg-slate-100'
            }`}
          >
            <t.icon size={15} /> {t.label}
            <span
              className={`grid min-w-5 place-items-center rounded-full px-1.5 py-0.5 text-[10px] font-bold ${
                tab === t.key ? 'bg-white/20 text-white' : 'bg-slate-100 text-slate-500'
              }`}
            >
              {t.count}
            </span>
          </button>
        ))}
      </div>

      <div key={tab} className="animate-fade-in">
        {tab === 'invites' ? <InvitesTab invites={invites} /> : <AvailabilityTab list={availability} />}
      </div>
    </div>
  )
}

export function CustomersSelect({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const customers = useQuery({ queryKey: ['customers'], queryFn: () => customerApi.list({ limit: 500 }) })
  return (
    <select className={selectCls} value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">Select customer…</option>
      {customers.data?.map((c) => (
        <option key={c.id} value={c.id}>
          {c.customer_name || c.account_name} (id {c.id}) · {c.email}
        </option>
      ))}
    </select>
  )
}

// ------------------------------------------------------------------ invites
function InvitesTab({ invites }: { invites: { data?: MeetingInvite[]; isLoading: boolean } }) {
  const queryClient = useQueryClient()
  const [showForm, setShowForm] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<'all' | 'upcoming' | 'past'>('all')
  const [form, setForm] = useState({
    customer_id: '',
    recipient_email: '',
    subject: '',
    meeting_link: '',
    agenda: '',
    required_data: '',
    scheduled_at: '',
  })

  const create = useMutation({
    mutationFn: () =>
      meetingApi.createInvite({
        customer_id: Number(form.customer_id),
        recipient_email: form.recipient_email || null,
        subject: form.subject || null,
        meeting_link: form.meeting_link,
        agenda: form.agenda || null,
        required_data: form.required_data || null,
        scheduled_at: form.scheduled_at ? new Date(form.scheduled_at).toISOString() : null,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['meeting-invites'] })
      queryClient.invalidateQueries({ queryKey: ['email-logs'] })
      setShowForm(false)
      setError(null)
      setForm({ customer_id: '', recipient_email: '', subject: '', meeting_link: '', agenda: '', required_data: '', scheduled_at: '' })
    },
    onError: (e) => setError(e instanceof Error ? e.message : 'Create failed'),
  })

  const remove = useMutation({
    mutationFn: (id: number) => meetingApi.deleteInvite(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['meeting-invites'] }),
  })

  const FILTERS = [
    { key: 'all', label: 'All' },
    { key: 'upcoming', label: 'Upcoming' },
    { key: 'past', label: 'Past' },
  ] as const

  const rows = (invites.data ?? []).filter((i) => {
    if (filter === 'all') return true
    const t = i.scheduled_at ? new Date(i.scheduled_at).getTime() : null
    if (filter === 'upcoming') return t != null && t >= Date.now()
    return t != null && t < Date.now()
  })

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
      {showForm && (
        <Panel className="scroll-fade h-fit lg:col-span-1">
          <div className="flex items-center justify-between">
            <PanelTitle>
              <Mail size={15} className="text-brand-teal" /> New invite
            </PanelTitle>
            <button onClick={() => setShowForm(false)} className="text-slate-400 hover:text-slate-600">
              <X size={18} />
            </button>
          </div>
          <div className="space-y-3">
            <Field label="Customer">
              <CustomersSelect value={form.customer_id} onChange={(v) => setForm({ ...form, customer_id: v })} />
            </Field>
            <Field label="Meeting link">
              <input
                className={inputCls}
                placeholder="https://teams.google.com/…"
                value={form.meeting_link}
                onChange={(e) => setForm({ ...form, meeting_link: e.target.value })}
              />
            </Field>
            <Field label="Recipient (defaults to customer email)">
              <input
                className={inputCls}
                type="email"
                placeholder="someone@company.com"
                value={form.recipient_email}
                onChange={(e) => setForm({ ...form, recipient_email: e.target.value })}
              />
            </Field>
            <Field label="Subject">
              <input
                className={inputCls}
                placeholder="Meeting with Ambifo"
                value={form.subject}
                onChange={(e) => setForm({ ...form, subject: e.target.value })}
              />
            </Field>
            <Field label="Scheduled at">
              <input
                className={inputCls}
                type="datetime-local"
                value={form.scheduled_at}
                onChange={(e) => setForm({ ...form, scheduled_at: e.target.value })}
              />
            </Field>
            <Field label="Agenda">
              <textarea
                className={inputCls}
                rows={3}
                value={form.agenda}
                onChange={(e) => setForm({ ...form, agenda: e.target.value })}
              />
            </Field>
            <Field label="Required data / materials">
              <textarea
                className={inputCls}
                rows={3}
                value={form.required_data}
                onChange={(e) => setForm({ ...form, required_data: e.target.value })}
              />
            </Field>
            {error && <p className="text-xs font-semibold text-red-600">{error}</p>}
            <Button
              className="w-full"
              icon={<Plus size={16} />}
              disabled={!form.customer_id || !form.meeting_link || create.isPending}
              onClick={() => create.mutate()}
            >
              Create & send invite
            </Button>
          </div>
        </Panel>
      )}
      <div className={`${showForm ? 'lg:col-span-2' : 'lg:col-span-3'}`}>
        <Panel className="scroll-fade">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <PanelTitle>
              <Mail size={15} className="text-brand-teal" /> Invites
            </PanelTitle>
            <div className="flex items-center gap-2">
              <div className="flex gap-1 rounded-xl border border-slate-200 bg-slate-50 p-0.5">
                {FILTERS.map((f) => (
                  <button
                    key={f.key}
                    onClick={() => setFilter(f.key)}
                    className={`rounded-lg px-2.5 py-1 font-display text-xs font-bold transition-colors ${
                      filter === f.key ? 'bg-white text-brand-teal-dark shadow-sm' : 'text-slate-400 hover:text-slate-600'
                    }`}
                  >
                    {f.label}
                  </button>
                ))}
              </div>
              {!showForm && (
                <Button variant="outline" icon={<Plus size={15} />} onClick={() => setShowForm(true)}>
                  New invite
                </Button>
              )}
            </div>
          </div>

          {invites.isLoading ? (
            <Spinner label="Loading invites" />
          ) : !rows.length ? (
            <EmptyState
              message={invites.data?.length ? 'No invites match this filter' : 'No meeting invites yet'}
            />
          ) : (
            <div className="space-y-3">
              {rows.map((i: MeetingInvite) => {
                const rel = relTime(i.scheduled_at)
                return (
                  <div
                    key={i.id}
                    className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm transition-all duration-300 hover:-translate-y-0.5 hover:border-brand-teal/30 hover:shadow-lg"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="flex min-w-0 items-start gap-3">
                        <span className="grid h-11 w-11 shrink-0 place-items-center rounded-2xl bg-gradient-to-br from-brand-teal to-brand-cyan font-display text-sm font-bold text-white shadow-md shadow-brand-teal/30">
                          {initials(i.customer_name ?? `Customer ${i.customer_id}`)}
                        </span>
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <h3 className="font-display text-sm font-bold text-navy-900">
                              {i.subject || 'Meeting invite'}
                            </h3>
                            <Badge tone="navy">
                              <Building2 size={11} /> {i.customer_name ?? `Customer #${i.customer_id}`}
                            </Badge>
                          </div>
                          <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500">
                            <span className="inline-flex items-center gap-1.5">
                              <Mail size={12} className="text-brand-teal" /> {i.recipient_email}
                            </span>
                            {i.created_by && <span>by {i.created_by}</span>}
                            <span className="text-slate-400">created {fmtDateTime(i.created_at)}</span>
                          </div>
                        </div>
                      </div>
                    </div>

                    {(i.agenda || i.required_data) && (
                      <div className="mt-4 grid gap-3 rounded-xl border border-slate-100 bg-slate-50/70 p-4 sm:grid-cols-2">
                        {i.agenda && (
                          <div>
                            <div className="mb-1 flex items-center gap-1 font-display text-[10px] font-bold uppercase tracking-widest text-slate-400">
                              <ListTodo size={12} className="text-brand-teal" /> Agenda
                            </div>
                            <p className="whitespace-pre-line text-sm text-slate-600">{i.agenda}</p>
                          </div>
                        )}
                        {i.required_data && (
                          <div>
                            <div className="mb-1 flex items-center gap-1 font-display text-[10px] font-bold uppercase tracking-widest text-slate-400">
                              <ClipboardList size={12} className="text-brand-teal" /> Required data
                            </div>
                            <p className="whitespace-pre-line text-sm text-slate-600">{i.required_data}</p>
                          </div>
                        )}
                      </div>
                    )}

                    <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-4">
                      <div className="flex items-center gap-2">
                        <span className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs text-slate-500">
                          <CalendarClock size={12} /> {i.scheduled_at ? fmtDateTime(i.scheduled_at) : 'No date set'}
                        </span>
                        {i.scheduled_at && rel && (
                          <span
                            className={`text-xs font-semibold ${rel.upcoming ? 'text-brand-teal-dark' : 'text-slate-400'}`}
                          >
                            {rel.label}
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-2">
                        <a
                          href={i.meeting_link}
                          target="_blank"
                          rel="noreferrer"
                          className="inline-flex items-center gap-1.5 rounded-lg bg-gradient-to-r from-brand-teal to-brand-teal-dark px-3 py-1.5 font-display text-xs font-bold text-white shadow-md shadow-brand-teal/25 transition-all hover:-translate-y-0.5"
                        >
                          Join meeting <ExternalLink size={12} />
                        </a>
                        <button
                          onClick={() => remove.mutate(i.id)}
                          className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-red-50 hover:text-red-600"
                          title="Delete invite"
                        >
                          <X size={16} />
                        </button>
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </Panel>
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ availability
function AvailabilityTab({ list }: { list: { data?: MeetingAvailability[]; isLoading: boolean } }) {
  const queryClient = useQueryClient()
  const [showForm, setShowForm] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<'all' | 'pending' | 'responded' | 'expired'>('all')
  const [form, setForm] = useState({ customer_id: '', option_1_at: '', option_2_at: '', option_3_at: '', recipient_email: '', expires_days: '7' })

  const create = useMutation({
    mutationFn: () =>
      meetingApi.createAvailability({
        customer_id: Number(form.customer_id),
        option_1_at: toISO(form.option_1_at),
        option_2_at: toISO(form.option_2_at),
        option_3_at: toISO(form.option_3_at),
        recipient_email: form.recipient_email || null,
        expires_days: Number(form.expires_days) || 7,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['meeting-availability'] })
      queryClient.invalidateQueries({ queryKey: ['email-logs'] })
      setShowForm(false)
      setError(null)
    },
    onError: (e) => setError(e instanceof Error ? e.message : 'Create failed'),
  })

  const optionsValid = form.option_1_at && form.option_2_at && form.option_3_at

  const FILTERS = [
    { key: 'all', label: 'All' },
    { key: 'pending', label: 'Pending' },
    { key: 'responded', label: 'Responded' },
    { key: 'expired', label: 'Expired' },
  ] as const

  const rows = (list.data ?? []).filter((a) => {
    if (filter === 'all') return true
    if (filter === 'pending') return a.status === 'sent' && (!a.expires_at || new Date(a.expires_at) > new Date())
    if (filter === 'responded') return a.status === 'selected' || a.status === 'submitted-form'
    return a.status === 'expired'
  })

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
      {showForm && (
        <Panel className="scroll-fade h-fit lg:col-span-1">
          <div className="flex items-center justify-between">
            <PanelTitle>
              <CalendarClock size={15} className="text-brand-teal" /> New availability request
            </PanelTitle>
            <button onClick={() => setShowForm(false)} className="text-slate-400 hover:text-slate-600">
              <X size={18} />
            </button>
          </div>
          <div className="space-y-3">
            <Field label="Customer">
              <CustomersSelect value={form.customer_id} onChange={(v) => setForm({ ...form, customer_id: v })} />
            </Field>
            {[1, 2, 3].map((n) => (
              <Field key={n} label={`Option ${n} — suggested time`}>
                <input
                  className={inputCls}
                  type="datetime-local"
                  value={form[`option_${n}_at` as keyof typeof form] as string}
                  onChange={(e) => setForm({ ...form, [`option_${n}_at`]: e.target.value } as typeof form)}
                />
              </Field>
            ))}
            <Field label="Recipient (defaults to customer email)">
              <input
                className={inputCls}
                type="email"
                placeholder="someone@company.com"
                value={form.recipient_email}
                onChange={(e) => setForm({ ...form, recipient_email: e.target.value })}
              />
            </Field>
            <Field label="Expires in (days)">
              <input
                className={inputCls}
                type="number"
                min={1}
                value={form.expires_days}
                onChange={(e) => setForm({ ...form, expires_days: e.target.value })}
              />
            </Field>
            {error && <p className="text-xs font-semibold text-red-600">{error}</p>}
            <Button
              className="w-full"
              icon={<Plus size={16} />}
              disabled={!form.customer_id || !optionsValid || create.isPending}
              onClick={() => create.mutate()}
            >
              Create & email the link
            </Button>
          </div>
        </Panel>
      )}
      <div className={`${showForm ? 'lg:col-span-2' : 'lg:col-span-3'}`}>
        <Panel className="scroll-fade">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <PanelTitle>
              <CalendarClock size={15} className="text-brand-teal" /> Availability requests
            </PanelTitle>
            <div className="flex items-center gap-2">
              <div className="flex gap-1 rounded-xl border border-slate-200 bg-slate-50 p-0.5">
                {FILTERS.map((f) => (
                  <button
                    key={f.key}
                    onClick={() => setFilter(f.key)}
                    className={`rounded-lg px-2.5 py-1 font-display text-xs font-bold transition-colors ${
                      filter === f.key ? 'bg-white text-brand-teal-dark shadow-sm' : 'text-slate-400 hover:text-slate-600'
                    }`}
                  >
                    {f.label}
                  </button>
                ))}
              </div>
              {!showForm && (
                <Button variant="outline" icon={<Plus size={15} />} onClick={() => setShowForm(true)}>
                  New request
                </Button>
              )}
            </div>
          </div>

          {list.isLoading ? (
            <Spinner label="Loading requests" />
          ) : !rows.length ? (
            <EmptyState
              message={list.data?.length ? 'No requests match this filter' : 'No availability requests yet'}
            />
          ) : (
            <div className="space-y-3">
              {rows.map((a: MeetingAvailability) => {
                const meta = statusMeta(a.status)
                const exp = expiresIn(a.expires_at)
                const original = [a.option_1_at, a.option_2_at, a.option_3_at]
                const custom = [a.customer_option_1_at, a.customer_option_2_at, a.customer_option_3_at].filter(
                  (x): x is string => Boolean(x),
                )
                return (
                  <div
                    key={a.id}
                    className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm transition-all duration-300 hover:-translate-y-0.5 hover:border-brand-teal/30 hover:shadow-lg"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="flex min-w-0 items-start gap-3">
                        <span className="grid h-11 w-11 shrink-0 place-items-center rounded-2xl bg-gradient-to-br from-violet-500 to-indigo-600 font-display text-sm font-bold text-white shadow-md shadow-violet-500/30">
                          {initials(a.customer_name ?? `Customer ${a.customer_id}`)}
                        </span>
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <h3 className="font-display text-sm font-bold text-navy-900">
                              {a.subject || 'Availability request'}
                            </h3>
                          </div>
                          <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500">
                            <span className="inline-flex items-center gap-1.5">
                              <Building2 size={12} className="text-brand-teal" />{' '}
                              {a.customer_name ?? `Customer #${a.customer_id}`}
                            </span>
                            <span className="inline-flex items-center gap-1.5">
                              <Mail size={12} className="text-brand-teal" /> {a.recipient_email}
                            </span>
                            {a.extra_recipients && (
                              <span className="inline-flex items-center gap-1.5">
                                <Users size={12} className="text-brand-teal" /> +{a.extra_recipients}
                              </span>
                            )}
                          </div>
                        </div>
                      </div>
                      <div className="flex shrink-0 items-center gap-2">
                        <Badge tone={meta.tone}>{meta.label}</Badge>
                        {exp && exp.label !== 'Expired' && (
                          <Badge tone={exp.expiresSoon ? 'coral' : 'neutral'}>{exp.label}</Badge>
                        )}
                      </div>
                    </div>

                    <div className="mt-4">
                      <div className="mb-1.5 flex items-center gap-1 font-display text-[10px] font-bold uppercase tracking-widest text-slate-400">
                        <CalendarClock size={12} className="text-brand-teal" /> Suggested times
                      </div>
                      <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                        {original.map((o, idx) => {
                          const isSelected = a.selected_option === idx + 1
                          const customMatch = a.status === 'submitted-form'
                          return (
                            <div
                              key={idx}
                              className={`flex items-center justify-between gap-2 rounded-xl border px-3.5 py-2.5 ${
                                isSelected && !customMatch
                                  ? 'border-brand-teal/40 bg-brand-teal/5'
                                  : 'border-slate-100 bg-slate-50/50'
                              }`}
                            >
                              <div className="flex items-center gap-2.5">
                                <span
                                  className={`grid h-6 w-6 shrink-0 place-items-center rounded-full font-display text-[11px] font-bold ${
                                    isSelected && !customMatch
                                      ? 'bg-brand-teal text-white'
                                      : 'bg-slate-200 text-slate-500'
                                  }`}
                                >
                                  {idx + 1}
                                </span>
                                <span className="text-sm font-semibold text-navy-900">{fmtDateTime(o)}</span>
                              </div>
                              {isSelected && !customMatch && (
                                <span className="inline-flex items-center gap-1 text-xs font-bold text-brand-teal-dark">
                                  <Check size={13} /> Selected
                                </span>
                              )}
                            </div>
                          )
                        })}
                      </div>

                      {custom.length > 0 && (
                        <>
                          <div className="mb-1.5 mt-3 flex items-center gap-1 font-display text-[10px] font-bold uppercase tracking-widest text-slate-400">
                            <CalendarCheck size={12} className="text-violet-500" /> Customer's proposed times
                          </div>
                          <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                            {custom.map((o, idx) => (
                              <div
                                key={idx}
                                className="flex items-center gap-2.5 rounded-xl border border-violet-200 bg-violet-50/50 px-3.5 py-2.5"
                              >
                                <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-violet-500 font-display text-[11px] font-bold text-white">
                                  {idx + 1}
                                </span>
                                <span className="text-sm font-semibold text-navy-900">{fmtDateTime(o)}</span>
                              </div>
                            ))}
                          </div>
                        </>
                      )}
                    </div>

                    {a.customer_note && (
                      <div className="mt-4 flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
                        <MessageSquare size={14} className="mt-0.5 shrink-0 text-amber-500" />
                        <span>
                          <span className="font-display text-xs font-bold uppercase tracking-wide">Note from customer: </span>
                          {a.customer_note}
                        </span>
                      </div>
                    )}

                    <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-4">
                      <div className="flex items-center gap-2 text-xs text-slate-400">
                        {a.selected_option && a.selected_at ? (
                          <span className="inline-flex items-center gap-1.5">
                            <Check size={13} className="text-brand-teal" /> Picked {fmtDateTime(a.selected_at)}
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1.5">
                            <Clock3 size={12} /> created {fmtDateTime(a.created_at)}
                          </span>
                        )}
                        {exp?.label === 'Expired' && <span>· link expired</span>}
                      </div>
                      <div className="flex items-center gap-2">
                        <a
                          href={`${ORIGIN}/public/meetings/${a.token}`}
                          target="_blank"
                          rel="noreferrer"
                          className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-2.5 py-1.5 font-display text-xs font-bold text-slate-600 transition-colors hover:border-brand-teal hover:text-brand-teal-dark"
                          title="Open public page"
                        >
                          <ExternalLink size={13} /> View
                        </a>
                        <button
                          onClick={() => copy(`${ORIGIN}/public/meetings/${a.token}`)}
                          className="inline-flex items-center gap-1 rounded-lg bg-gradient-to-r from-brand-teal to-brand-teal-dark px-2.5 py-1.5 font-display text-xs font-bold text-white shadow-md shadow-brand-teal/25 transition-all hover:-translate-y-0.5"
                          title="Copy public link"
                        >
                          <Copy size={13} /> Copy link
                        </button>
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </Panel>
      </div>
    </div>
  )
}