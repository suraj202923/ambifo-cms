import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { ArrowRight, CheckCircle2, ChevronLeft, ChevronRight, Pencil, Plus, Search, Target, Trash2, Users, X } from 'lucide-react'
import { leadApi } from '../api'
import type { Lead, LeadCreate, LeadStats } from '../api/types'
import { Badge, Button, EmptyState, Field, inputCls, PageHead, selectCls, Spinner } from '../components/ui'

const PAGE_SIZE = 20
const STATUSES = ['new', 'contacted', 'qualified', 'converted', 'lost']

function useDebounced<T>(value: T, delay = 300): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(t)
  }, [value, delay])
  return debounced
}

const EMPTY_FORM: LeadCreate = {
  lead_name: '',
  email: '',
  phone: '',
  company: '',
  city: '',
  source: '',
  tags: '',
  notes: '',
  lead_status: 'new',
}

function toForm(l: Lead): LeadCreate {
  return {
    lead_name: l.lead_name,
    email: l.email,
    phone: l.phone,
    company: l.company,
    city: l.city,
    source: l.source,
    tags: l.tags,
    notes: l.notes,
    lead_status: l.lead_status,
  }
}

export default function LeadsPage() {
  const queryClient = useQueryClient()
  const [search, setSearch] = useState('')
  const debouncedSearch = useDebounced(search)
  const [status, setStatus] = useState('')
  const [page, setPage] = useState(1)
  const [showForm, setShowForm] = useState(false)
  const [editing, setEditing] = useState<Lead | null>(null)
  const [form, setForm] = useState<LeadCreate>(EMPTY_FORM)
  const [formError, setFormError] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<Lead | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [sortKey, setSortKey] = useState<'name' | 'status' | 'created'>('name')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc')

  const { data: leads, isLoading, isError } = useQuery({
    queryKey: ['leads', debouncedSearch, status, page],
    queryFn: () => leadApi.list({ search: debouncedSearch || undefined, lead_status: status || undefined, limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE }),
  })
  const { data: stats } = useQuery<LeadStats>({
    queryKey: ['lead-stats', debouncedSearch],
    queryFn: () => leadApi.stats(debouncedSearch || undefined),
  })

  const createMutation = useMutation({
    mutationFn: (payload: LeadCreate) =>
      editing ? leadApi.update(editing.id, payload) : leadApi.create(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['leads'] })
      queryClient.invalidateQueries({ queryKey: ['lead-stats'] })
      queryClient.invalidateQueries({ queryKey: ['dashboard'] })
      setShowForm(false)
      setEditing(null)
      setForm(EMPTY_FORM)
    },
    onError: (e) => setFormError(e instanceof Error ? e.message : 'Save failed'),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => leadApi.remove(id),
    onSuccess: () => {
      setConfirmDelete(null)
      queryClient.invalidateQueries({ queryKey: ['leads'] })
      queryClient.invalidateQueries({ queryKey: ['lead-stats'] })
      queryClient.invalidateQueries({ queryKey: ['dashboard'] })
    },
    onError: (e) => setError(e instanceof Error ? e.message : 'Delete failed'),
  })

  const convertMutation = useMutation({
    mutationFn: leadApi.convert,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['leads'] })
      queryClient.invalidateQueries({ queryKey: ['lead-stats'] })
      queryClient.invalidateQueries({ queryKey: ['customers'] })
      queryClient.invalidateQueries({ queryKey: ['dashboard'] })
    },
  })

  const statusMutation = useMutation({
    mutationFn: ({ id, lead_status }: { id: number; lead_status: string }) =>
      leadApi.update(id, { lead_status }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['leads'] })
      queryClient.invalidateQueries({ queryKey: ['lead-stats'] })
    },
  })

  function set<K extends keyof LeadCreate>(key: K, value: LeadCreate[K]) {
    setForm((f) => ({ ...f, [key]: value }))
  }

  function openCreate() {
    setEditing(null)
    setForm(EMPTY_FORM)
    setFormError(null)
    setShowForm((v) => !v)
  }

  function startEdit(l: Lead) {
    setEditing(l)
    setForm(toForm(l))
    setFormError(null)
    setShowForm(true)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  function handleDelete(l: Lead) {
    setError(null)
    setConfirmDelete(l)
  }

  const isConverted = (l: Lead) => l.converted_customer_id != null

  const total = stats?.total ?? leads?.length ?? 0
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const pageLeads = leads ? [...leads].sort((a, b) => {
    let cmp = 0
    if (sortKey === 'name') cmp = (a.lead_name ?? '').localeCompare(b.lead_name ?? '')
    else if (sortKey === 'status') cmp = a.lead_status.localeCompare(b.lead_status)
    else if (sortKey === 'created') cmp = new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
    return sortDir === 'asc' ? cmp : -cmp
  }) : []

  function toggleSort(key: 'name' | 'status' | 'created') {
    if (sortKey === key) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    else { setSortKey(key); setSortDir('asc') }
  }
  const sortArrow = (key: 'name' | 'status' | 'created') =>
    sortKey === key ? (sortDir === 'asc' ? ' ▲' : ' ▼') : ''

  function formatRelative(iso: string) {
    const diff = Date.now() - new Date(iso).getTime()
    const mins = Math.floor(diff / 60000)
    if (mins < 1) return 'just now'
    if (mins < 60) return `${mins}m ago`
    const hrs = Math.floor(mins / 60)
    if (hrs < 24) return `${hrs}h ago`
    const days = Math.floor(hrs / 24)
    if (days < 30) return `${days}d ago`
    return new Date(iso).toLocaleDateString()
  }

  const kpiStrip = [
    { label: 'Total leads', value: stats?.total ?? 0, sub: stats?.total ? 'all active' : 'pipeline', icon: Users, bg: 'from-brand-teal to-brand-teal-dark' },
    { label: 'New', value: stats?.new ?? 0, sub: 'uncaptured', icon: Plus, bg: 'from-brand-cyan to-brand-teal' },
    { label: 'Qualified', value: stats?.qualified ?? 0, sub: `${stats?.contacted ?? 0} contacted`, icon: Target, bg: 'from-green-500 to-emerald-600' },
    { label: 'Converted', value: stats?.converted ?? 0, sub: 'moved to customers', icon: CheckCircle2, bg: 'from-navy-700 to-navy-900' },
  ]

  const hasFilter = search.trim() !== '' || status !== ''

  return (
    <div>
      <PageHead
        title="Leads"
        subtitle={`${total.toLocaleString()} leads across your funnel`}
        actions={
          <Button icon={<Plus size={16} />} onClick={openCreate}>
            {showForm ? 'Close' : 'Add lead'}
          </Button>
        }
      />

      <div className="stagger mb-6 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {kpiStrip.map((k) => (
          <div
            key={k.label}
            className="group relative overflow-hidden rounded-2xl border border-slate-200 bg-white p-5 shadow-sm transition-all duration-300 hover:-translate-y-1 hover:shadow-xl hover:shadow-navy-900/10"
          >
            <div className={`absolute -right-6 -top-6 h-24 w-24 rounded-full bg-gradient-to-br ${k.bg} opacity-[0.08] transition-transform duration-500 group-hover:scale-150`} />
            <div className="flex items-center justify-between">
              <span className="font-display text-xs font-bold tracking-widest text-slate-500 uppercase">{k.label}</span>
              <span className={`flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br ${k.bg} text-white shadow-md`}>
                <k.icon size={17} />
              </span>
            </div>
            <div className="mt-3 font-display text-3xl font-bold text-navy-900">{k.value}</div>
            <div className="mt-1 text-xs text-slate-500">{k.sub}</div>
          </div>
        ))}
      </div>

      {showForm && (
        <form
          className="scroll-fade brand-card mb-6 rounded-2xl border border-brand-teal/30 bg-white p-6 shadow-lg shadow-brand-teal/5"
          onSubmit={(e) => {
            e.preventDefault()
            setFormError(null)
            createMutation.mutate(form)
          }}
        >
          <div className="mb-5 flex items-center gap-2">
            <Users size={16} className="text-brand-teal" />
            <h2 className="font-display text-sm font-bold tracking-wide text-navy-900 uppercase">
              {editing ? `Edit · ${editing.lead_name ?? 'lead'}` : 'New lead'}
            </h2>
            <button type="button" className="ml-auto text-slate-400 hover:text-slate-600" onClick={() => setShowForm(false)}>
              <X size={18} />
            </button>
          </div>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <Field label="Lead name">
              <input className={inputCls} value={form.lead_name ?? ''} onChange={(e) => set('lead_name', e.target.value)} placeholder="Jane Doe" />
            </Field>
            <Field label="Email">
              <input type="email" className={inputCls} value={form.email ?? ''} onChange={(e) => set('email', e.target.value)} placeholder="jane@company.com" />
            </Field>
            <Field label="Phone">
              <input className={inputCls} value={form.phone ?? ''} onChange={(e) => set('phone', e.target.value)} />
            </Field>
            <Field label="Company">
              <input className={inputCls} value={form.company ?? ''} onChange={(e) => set('company', e.target.value)} />
            </Field>
            <Field label="City">
              <input className={inputCls} value={form.city ?? ''} onChange={(e) => set('city', e.target.value)} />
            </Field>
            <Field label="Source">
              <input className={inputCls} value={form.source ?? ''} onChange={(e) => set('source', e.target.value)} list="lead-sources" />
              <datalist id="lead-sources">
                <option value="website" /><option value="referral" /><option value="linkedin" /><option value="email" /><option value="event" />
              </datalist>
            </Field>
            <Field label="Tags">
              <input className={inputCls} value={form.tags ?? ''} onChange={(e) => set('tags', e.target.value)} placeholder="comma, separated" />
            </Field>
            <Field label="Status">
              <select className={selectCls} value={form.lead_status ?? 'new'} onChange={(e) => set('lead_status', e.target.value as LeadCreate['lead_status'])}>
                {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </Field>
          </div>
          <Field label="Notes">
            <textarea
              className={`${inputCls} mt-4 min-h-[80px]`}
              value={form.notes ?? ''}
              onChange={(e) => set('notes', e.target.value)}
            />
          </Field>
          {formError && <div className="mt-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-600">⚠ {formError}</div>}
          <div className="mt-5 flex gap-2">
            <Button disabled={createMutation.isPending} type="submit">{createMutation.isPending ? 'Saving…' : editing ? 'Save changes' : 'Save lead'}</Button>
            <Button type="button" variant="ghost" onClick={() => setShowForm(false)}>Cancel</Button>
          </div>
        </form>
      )}

      <div className="stagger mb-4 flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[220px]">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            className={`${inputCls} pl-9`}
            placeholder="Search name, email, company…"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value)
              setPage(1)
            }}
          />
        </div>
        <select
          className={`${selectCls} w-auto`}
          value={status}
          onChange={(e) => {
            setStatus(e.target.value)
            setPage(1)
          }}
        >
          <option value="">All statuses</option>
          {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </div>

      {error && (
        <div className="mb-4 flex items-center justify-between rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-600">
          <span>{error}</span>
          <button type="button" className="font-semibold text-red-500 hover:text-red-700" onClick={() => setError(null)}>Dismiss</button>
        </div>
      )}

      {isError ? (
        <div className="rounded-2xl border border-red-200 bg-red-50 p-6 text-red-600">
          Failed to load leads. Please try again.
        </div>
      ) : isLoading ? (
        <Spinner label="Loading leads" />
      ) : (
        <div className="scroll-fade brand-card overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
          <div className="flex items-center justify-between border-b border-slate-100 bg-gradient-to-r from-brand-teal/5 via-white to-white px-5 py-3">
            <span className="font-display text-xs font-bold tracking-widest text-slate-500 uppercase">
              Lead funnel
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-full bg-brand-teal/10 px-2.5 py-1 text-xs font-bold text-brand-teal-dark">
              {pageLeads.length} shown{hasFilter ? ' · filtered' : ''}
            </span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-slate-100 bg-slate-50/80 font-display text-[11px] font-bold tracking-widest text-slate-500 uppercase">
                  <th className="px-5 py-3.5">
                    <button type="button" className="hover:text-brand-teal-dark" onClick={() => toggleSort('name')}>Name{sortArrow('name')}</button>
                  </th>
                  <th className="px-5 py-3.5">Company</th>
                  <th className="px-5 py-3.5">Email</th>
                  <th className="px-5 py-3.5">Source</th>
                  <th className="px-5 py-3.5">
                    <button type="button" className="hover:text-brand-teal-dark" onClick={() => toggleSort('status')}>Status{sortArrow('status')}</button>
                  </th>
                  <th className="px-5 py-3.5">Tags</th>
                  <th className="px-5 py-3.5 text-right">
                    <button type="button" className="hover:text-brand-teal-dark" onClick={() => toggleSort('created')}>Added{sortArrow('created')}</button>
                  </th>
                  <th className="px-5 py-3.5 text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {pageLeads.map((lead) => (
                  <tr key={lead.id} className="group border-b border-slate-50 transition-colors last:border-0 hover:bg-brand-teal/[0.04]">
                    <td className="px-5 py-3.5">
                      <div className="flex items-center gap-2.5">
                        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-brand-teal to-brand-teal-dark font-display text-sm font-bold text-white shadow-sm transition-transform duration-300 group-hover:scale-105">
                          {(lead.lead_name ?? '?').slice(0, 1).toUpperCase()}
                        </span>
                        <div className="min-w-0">
                          <div className="truncate font-semibold text-navy-900">{lead.lead_name ?? '—'}</div>
                          {lead.notes && (
                            <div className="max-w-[220px] truncate text-xs text-slate-400" title={lead.notes}>{lead.notes}</div>
                          )}
                        </div>
                      </div>
                    </td>
                    <td className="px-5 py-3.5 text-slate-600">{lead.company ?? '—'}</td>
                    <td className="px-5 py-3.5 text-slate-600">{lead.email ?? '—'}</td>
                    <td className="px-5 py-3.5">
                      {lead.source ? <Badge tone="navy">{lead.source}</Badge> : <span className="text-slate-400">—</span>}
                    </td>
                    <td className="px-5 py-3.5">
                      {isConverted(lead) ? (
                        <Badge tone="green">Converted</Badge>
                      ) : (
                        <select
                          className="cursor-pointer rounded-full border border-slate-200 bg-white px-2.5 py-1 text-xs font-semibold text-slate-700 outline-none transition-all focus:ring-2 focus:ring-brand-teal/30"
                          value={lead.lead_status}
                          onChange={(e) => statusMutation.mutate({ id: lead.id, lead_status: e.target.value })}
                        >
                          {STATUSES.map((s) => <option key={s} value={s}>{s.charAt(0).toUpperCase() + s.slice(1)}</option>)}
                        </select>
                      )}
                    </td>
                    <td className="px-5 py-3.5">
                      {lead.tags ? (
                        <div className="flex max-w-[180px] flex-wrap gap-1">
                          {lead.tags.split(',').map((t) => <Badge key={t} tone="neutral">{t.trim()}</Badge>)}
                        </div>
                      ) : (
                        <span className="text-slate-400">—</span>
                      )}
                    </td>
                    <td className="px-5 py-3.5 text-right">
                      <span className="text-xs text-slate-400" title={new Date(lead.created_at).toLocaleString()}>{formatRelative(lead.created_at)}</span>
                    </td>
                    <td className="px-5 py-3.5">
                      <div className="flex items-center justify-end gap-1">
                        <button
                          type="button"
                          className="rounded-lg p-1.5 text-slate-300 transition-colors hover:bg-brand-teal/10 hover:text-brand-teal-dark"
                          title="Edit"
                          onClick={() => startEdit(lead)}
                        >
                          <Pencil size={14} />
                        </button>
                        {!isConverted(lead) && (
                          <Button
                            variant="outline"
                            className="!px-2.5 !py-1.5 !text-xs"
                            onClick={() => convertMutation.mutate(lead.id)}
                            disabled={convertMutation.isPending}
                          >
                            {convertMutation.isPending ? 'Converting…' : 'Convert'}
                          </Button>
                        )}
                        {lead.converted_customer_id != null && (
                          <Link
                            to={`/customers/${lead.converted_customer_id}`}
                            className="inline-flex items-center gap-1 rounded-lg px-2.5 py-1.5 font-display text-xs font-bold text-brand-teal-dark transition-colors hover:bg-brand-teal/10"
                          >
                            View customer <ArrowRight size={13} />
                          </Link>
                        )}
                        <button
                          type="button"
                          className="rounded-lg p-1.5 text-slate-300 transition-colors hover:bg-red-50 hover:text-red-600"
                          title="Delete"
                          onClick={() => handleDelete(lead)}
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {pageLeads.length === 0 && (
            <EmptyState message={hasFilter ? 'No leads match your filter' : 'No leads yet — add one with the button above'} />
          )}
        </div>
      )}

      {totalPages > 1 && pageLeads.length > 0 && (
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-200 bg-white px-4 py-3 shadow-sm">
          <span className="text-sm text-slate-500">
            Showing <span className="font-semibold text-navy-900">{(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, total)}</span> of{' '}
            <span className="font-semibold text-navy-900">{total.toLocaleString()}</span>
          </span>
          <div className="flex items-center gap-1">
            <Button variant="ghost" icon={<ChevronLeft size={16} />} disabled={page <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))}>
              Prev
            </Button>
            <span className="min-w-[80px] text-center font-display text-xs font-bold tracking-widest text-slate-500 uppercase">
              Page {page} / {totalPages}
            </span>
            <Button variant="ghost" onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page >= totalPages}>
              Next <ChevronRight size={16} />
            </Button>
          </div>
        </div>
      )}

      {confirmDelete && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-navy-900/50 p-4 backdrop-blur-sm" onClick={() => setConfirmDelete(null)}>
          <div
            className="brand-card w-full max-w-sm rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
            role="alertdialog"
            aria-modal="true"
            aria-label="Confirm delete lead"
          >
            <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-red-50 text-red-600">
              <Trash2 size={22} />
            </div>
            <h3 className="font-display text-lg font-bold text-navy-900">Delete lead?</h3>
            <p className="mt-2 text-sm text-slate-500">
              <span className="font-semibold text-navy-800">{confirmDelete.lead_name ?? 'This lead'}</span>{' '}
              ({confirmDelete.email ?? 'no email'}) will be removed from your funnel.
            </p>
            <div className="mt-5 flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setConfirmDelete(null)}>Cancel</Button>
              <button
                type="button"
                className="inline-flex items-center gap-2 rounded-xl bg-red-600 px-4 py-2.5 font-display text-sm font-semibold text-white transition-all duration-300 hover:-translate-y-0.5 hover:bg-red-700 disabled:opacity-60"
                onClick={() => deleteMutation.mutate(confirmDelete.id)}
                disabled={deleteMutation.isPending}
              >
                <Trash2 size={15} />
                {deleteMutation.isPending ? 'Deleting…' : 'Delete'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}