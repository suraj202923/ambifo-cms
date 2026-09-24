import { useQuery } from '@tanstack/react-query'
import {
  Activity,
  ArrowDownRight,
  ArrowUpRight,
  Building2,
  DollarSign,
  Layers,
  PieChart,
  PlusCircle,
  Sparkles,
  Target,
  TrendingUp,
  Users,
} from 'lucide-react'
import { dashboardApi } from '../api'
import { Badge, PageLoading } from '../components/ui'
import { useAuth } from '../auth'

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

const KPI_STYLES = [
  {
    icon: Users,
    ring: 'from-brand-cyan to-brand-teal',
    glow: 'shadow-brand-cyan/30',
    chip: 'text-brand-teal',
  },
  {
    icon: Target,
    ring: 'from-teal-500 to-emerald-700',
    glow: 'shadow-teal-500/30',
    chip: 'text-teal-600',
  },
  {
    icon: TrendingUp,
    ring: 'from-violet-500 to-indigo-600',
    glow: 'shadow-violet-500/30',
    chip: 'text-violet-600',
  },
  {
    icon: DollarSign,
    ring: 'from-emerald-500 to-brand-green',
    glow: 'shadow-emerald-500/30',
    chip: 'text-emerald-600',
  },
]

const SECTION_TILE: Record<string, string> = {
  teal: 'from-brand-cyan to-brand-teal',
  sky: 'from-teal-500 to-emerald-700',
  violet: 'from-violet-500 to-indigo-600',
  emerald: 'from-emerald-500 to-brand-green',
  amber: 'from-amber-400 to-amber-600',
}

export default function DashboardPage() {
  const { user } = useAuth()
  const { data, isLoading, isError } = useQuery({
    queryKey: ['dashboard'],
    queryFn: dashboardApi.get,
  })

  if (isLoading) return <PageLoading label="Loading dashboard" />
  if (isError || !data)
    return <div className="rounded-2xl border border-red-200 bg-red-50 p-6 text-red-600">Failed to load dashboard</div>

  const { kpis, by_status, by_segment, by_assignee, recent_history, opportunities_by_month } = data
  const maxStatus = Math.max(...by_status.map((s) => s.count), 1)
  const maxSegment = Math.max(...by_segment.map((s) => s.count), 1)
  const maxMonth = Math.max(...opportunities_by_month.map((m) => m.count), 1)
  const maxAssignee = Math.max(...by_assignee.map((a) => a.count), 1)

  const kpisArr = [
    { label: 'Customers', value: kpis.total_customers, sub: `+${kpis.customers_added_30d} in last 30 days`, growth: '+', up: true },
    { label: 'Active Leads', value: kpis.total_leads, sub: 'in current pipeline', growth: '', up: true },
    { label: 'Open Opportunities', value: kpis.open_opportunities, sub: 'deals in progress', growth: '', up: true },
    { label: 'Actual MRR', value: `$${kpis.total_mrr.toLocaleString()}`, sub: `${kpis.total_arr.toLocaleString()} ARR`, growth: '', up: true },
  ]

  const today = new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })

  return (
    <div className="space-y-6">
      {/* ── Welcome hero ─────────────────────────────────────── */}
      <section className="ambiflow-hero relative overflow-hidden rounded-3xl border border-brand-teal/20 p-6 shadow-xl shadow-navy-900/10 sm:p-8">
        <div className="dot-grid" />
        <div className="glow-orb h-44 w-44 animate-float bg-brand-cyan/30" style={{ top: '-60px', right: '8%' }} />
        <div className="glow-orb h-44 w-44 animate-float bg-brand-teal/25" style={{ bottom: '-70px', right: '35%', animationDelay: '-3s' }} />

        <div className="relative z-10 flex flex-wrap items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <Sparkles size={16} className="text-brand-cyan" />
              <span className="font-display text-[11px] font-bold uppercase tracking-[0.25em] text-brand-cyan">
                {today}
              </span>
            </div>
            <h1 className="mt-2 font-display text-2xl font-bold text-white sm:text-3xl">
              Welcome back, {user?.full_name || user?.username}
            </h1>
            <p className="mt-1.5 text-sm text-slate-400">
              Here's what's happening across your cloud pipeline today.
            </p>
          </div>
          <div className="flex items-center gap-3">
            <div className="flex flex-col items-center rounded-2xl border border-white/10 bg-white/5 px-6 py-4 backdrop-blur-sm transition-colors hover:border-brand-cyan/40">
              <span className="font-display text-2xl font-bold text-white">
                {kpis.open_opportunities}
              </span>
              <span className="mt-0.5 font-display text-[10px] font-semibold uppercase tracking-widest text-brand-cyan">
                Open deals
              </span>
            </div>
            <div className="hidden flex-col items-center rounded-2xl border border-emerald-400/25 bg-emerald-500/10 px-6 py-4 backdrop-blur-sm transition-colors hover:border-emerald-400/50 sm:flex">
              <span className="font-display text-2xl font-bold text-emerald-300">
                {by_status.filter((s) => ['Won'].includes(s.name)).reduce((n, s) => n + s.count, 0) || 0}
              </span>
              <span className="mt-0.5 font-display text-[10px] font-semibold uppercase tracking-widest text-emerald-400">
                Won deals
              </span>
            </div>
          </div>
        </div>
      </section>

      {/* ── KPI cards ────────────────────────────────────────── */}
      <div className="stagger grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {kpisArr.map((k, i) => {
          const s = KPI_STYLES[i]
          return (
            <div
              key={k.label}
              className="group relative overflow-hidden rounded-2xl border border-slate-200 bg-white p-5 shadow-sm transition-all duration-300 hover:-translate-y-1 hover:shadow-xl hover:shadow-navy-900/10"
            >
              <div
                className={`absolute -right-8 -top-8 h-28 w-28 rounded-full bg-gradient-to-br ${s.ring} opacity-[0.07] transition-transform duration-500 group-hover:scale-150`}
              />
              <div className="relative">
                <div className="flex items-start justify-between">
                  <div>
                    <p className="font-display text-xs font-bold uppercase tracking-widest text-slate-500">
                      {k.label}
                    </p>
                    <p className="mt-2 font-display text-3xl font-bold text-navy-900">{k.value}</p>
                  </div>
                  <span
                    className={`flex h-11 w-11 items-center justify-center rounded-2xl bg-gradient-to-br ${s.ring} text-white shadow-lg ${s.glow}`}
                  >
                    <s.icon size={20} />
                  </span>
                </div>
                <div className="mt-3 flex items-center gap-1.5 border-t border-slate-100 pt-3">
                  {k.up ? (
                    <ArrowUpRight size={13} className={s.chip} />
                  ) : (
                    <ArrowDownRight size={13} className="text-red-500" />
                  )}
                  <span className="text-xs text-slate-500">{k.sub}</span>
                </div>
              </div>
            </div>
          )
        })}
      </div>

      {/* ── Deal status + Segments ───────────────────────────── */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <section className="brand-card scroll-fade rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="mb-5 flex items-center justify-between">
            <h2 className="flex items-center gap-2 font-display text-sm font-bold uppercase tracking-wide text-navy-900">
              <span className={`flex h-8 w-8 items-center justify-center rounded-xl bg-gradient-to-br ${SECTION_TILE.teal} text-white shadow-md shadow-brand-teal/20`}>
                <PieChart size={15} />
              </span>
              Deal status
            </h2>
            <Badge tone="teal">{by_status.reduce((n, s) => n + s.count, 0)} total</Badge>
          </div>
          {by_status.length === 0 ? (
            <p className="py-8 text-center text-sm text-slate-400">No data yet</p>
          ) : (
            <ul className="space-y-4">
              {[...by_status].sort((a, b) => b.count - a.count).map((s, i) => (
                <li key={s.name}>
                  <div className="mb-1.5 flex items-center justify-between">
                    <span className="inline-flex items-center gap-2 text-sm font-semibold text-slate-700">
                      <span className="h-2.5 w-2.5 rounded-full" style={{ background: s.color }} />
                      {s.name}
                    </span>
                    <span className="font-display text-sm font-bold text-navy-900">
                      {s.count}
                      <span className="ml-1 text-xs font-semibold text-slate-400">
                        {Math.round((s.count / maxStatus) * 100)}%
                      </span>
                    </span>
                  </div>
                  <div className="h-2.5 overflow-hidden rounded-full bg-slate-100">
                    <div
                      className="bar-fill h-full rounded-full"
                      style={{
                        width: `${(s.count / maxStatus) * 100}%`,
                        background: `linear-gradient(90deg, ${s.color}, ${s.color}cc)`,
                        animationDelay: `${i * 0.08}s`,
                      }}
                    />
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="brand-card scroll-fade rounded-2xl border border-slate-200 bg-white p-6 shadow-sm" style={{ animationDelay: '0.1s' }}>
          <div className="mb-5 flex items-center justify-between">
            <h2 className="flex items-center gap-2 font-display text-sm font-bold uppercase tracking-wide text-navy-900">
              <span className={`flex h-8 w-8 items-center justify-center rounded-xl bg-gradient-to-br ${SECTION_TILE.sky} text-white shadow-md shadow-sky-500/20`}>
                <Layers size={15} />
              </span>
              Segments
            </h2>
            <Badge tone="navy">{by_segment.reduce((n, s) => n + s.count, 0)} total</Badge>
          </div>
          {by_segment.length === 0 ? (
            <p className="py-8 text-center text-sm text-slate-400">No data yet</p>
          ) : (
            <ul className="space-y-4">
              {[...by_segment].sort((a, b) => b.count - a.count).map((s, i) => (
                <li key={s.name}>
                  <div className="mb-1.5 flex items-center justify-between">
                    <span className="inline-flex items-center gap-2 text-sm font-semibold text-slate-700">
                      <Building2 size={13} className="text-slate-400" />
                      {s.name}
                    </span>
                    <span className="font-display text-sm font-bold text-navy-900">
                      {s.count}
                      <span className="ml-1 text-xs font-semibold text-slate-400">
                        {Math.round((s.count / maxSegment) * 100)}%
                      </span>
                    </span>
                  </div>
                  <div className="h-2.5 overflow-hidden rounded-full bg-slate-100">
                    <div
                      className="bar-fill h-full rounded-full bg-gradient-to-r from-sky-500 to-brand-teal"
                      style={{ width: `${(s.count / maxSegment) * 100}%`, animationDelay: `${i * 0.08}s` }}
                    />
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      {/* ── Opportunities + Deals by owner ───────────────────── */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <section className="brand-card scroll-fade rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="mb-5 flex items-center justify-between">
            <h2 className="flex items-center gap-2 font-display text-sm font-bold uppercase tracking-wide text-navy-900">
              <span className={`flex h-8 w-8 items-center justify-center rounded-xl bg-gradient-to-br ${SECTION_TILE.violet} text-white shadow-md shadow-violet-500/20`}>
                <TrendingUp size={15} />
              </span>
              Opportunities added
            </h2>
            <Badge tone="cyan">Last 12 months</Badge>
          </div>
          {opportunities_by_month.length === 0 ? (
            <p className="py-8 text-center text-sm text-slate-400">No data yet</p>
          ) : (
            <div className="flex h-52 items-end gap-2 sm:gap-3">
              {opportunities_by_month.map((m, i) => {
                const [, monthNum] = m.month.split('-')
                return (
                  <div key={m.month} className="group flex flex-1 flex-col items-center gap-2">
                    <span className="font-display text-xs font-bold text-navy-900 opacity-0 transition-opacity group-hover:opacity-100">
                      {m.count}
                    </span>
                    <div className="flex w-full flex-1 items-end">
                      <div
                        className="bar-col-fill w-full rounded-t-lg bg-gradient-to-t from-indigo-700 via-violet-600 to-violet-400 transition-all duration-300 group-hover:from-brand-teal group-hover:to-brand-cyan"
                        style={{ height: `${Math.max((m.count / maxMonth) * 100, 4)}%`, animationDelay: `${i * 0.07}s` }}
                      />
                    </div>
                    <span className="font-display text-[10px] font-semibold uppercase text-slate-500">
                      {MONTHS[Number(monthNum) - 1]}
                    </span>
                  </div>
                )
              })}
            </div>
          )}
        </section>

        <section className="brand-card scroll-fade rounded-2xl border border-slate-200 bg-white p-6 shadow-sm" style={{ animationDelay: '0.1s' }}>
          <div className="mb-5 flex items-center justify-between">
            <h2 className="flex items-center gap-2 font-display text-sm font-bold uppercase tracking-wide text-navy-900">
              <span className={`flex h-8 w-8 items-center justify-center rounded-xl bg-gradient-to-br ${SECTION_TILE.emerald} text-white shadow-md shadow-emerald-500/20`}>
                <Users size={15} />
              </span>
              Deals by owner
            </h2>
            <Badge tone="navy">{by_assignee.reduce((n, a) => n + a.count, 0)} deals</Badge>
          </div>
          {by_assignee.length === 0 ? (
            <p className="py-8 text-center text-sm text-slate-400">No data yet</p>
          ) : (
            <ul className="space-y-4">
              {[...by_assignee].sort((a, b) => b.count - a.count).map((a, i) => (
                <li key={a.name}>
                  <div className="mb-1.5 flex items-center justify-between">
                    <span className="inline-flex items-center gap-2 text-sm font-semibold text-slate-700">
                      <span className="flex h-6 w-6 items-center justify-center rounded-full bg-gradient-to-br from-emerald-500 to-brand-teal text-[10px] font-bold text-white">
                        {a.name.slice(0, 1).toUpperCase()}
                      </span>
                      {a.name}
                    </span>
                    <span className="font-display text-sm font-bold text-navy-900">{a.count}</span>
                  </div>
                  <div className="h-2.5 overflow-hidden rounded-full bg-slate-100">
                    <div
                      className="bar-fill h-full rounded-full bg-gradient-to-r from-emerald-500 to-brand-teal"
                      style={{ width: `${(a.count / maxAssignee) * 100}%`, animationDelay: `${i * 0.08}s` }}
                    />
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      {/* ── Recent activity ──────────────────────────────────── */}
      <section className="brand-card scroll-fade rounded-2xl border border-slate-200 bg-white p-6 shadow-sm" style={{ animationDelay: '0.1s' }}>
        <div className="mb-5 flex items-center justify-between">
<h2 className="flex items-center gap-2 font-display text-sm font-bold uppercase tracking-wide text-navy-900">
              <span className={`flex h-8 w-8 items-center justify-center rounded-xl bg-gradient-to-br ${SECTION_TILE.amber} text-white shadow-md shadow-amber-500/20`}>
                <Activity size={15} />
              </span>
              Recent activity
            </h2>
          <Badge tone="teal">{recent_history.length} events</Badge>
        </div>
        {recent_history.length === 0 ? (
          <div className="flex flex-col items-center gap-2 py-10 text-center text-slate-400">
            <PlusCircle size={28} className="text-amber-400" />
            <p className="font-display text-sm font-semibold">No activity yet</p>
            <p className="text-xs">Updates to your customers will appear here.</p>
          </div>
        ) : (
          <ul className="relative space-y-5 before:absolute before:bottom-2 before:left-[9px] before:top-2 before:w-px before:bg-gradient-to-b before:from-amber-400 before:via-slate-200 before:to-slate-200">
            {recent_history.map((h) => (
              <li key={h.id} className="relative pl-8">
                <span className="absolute left-0 top-1.5 flex h-[19px] w-[19px] items-center justify-center rounded-full border-2 border-white bg-gradient-to-br from-amber-400 to-amber-600 shadow-sm">
                  <span className="h-1.5 w-1.5 rounded-full bg-white" />
                </span>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-display text-sm font-bold capitalize text-navy-900">
                    {h.action.replace(/_/g, ' ')}
                  </span>
                  {h.tag_name && <Badge tone="cyan">{h.tag_name}</Badge>}
                  <span className="ml-auto text-xs text-slate-400">
                    {new Date(h.created_at ?? '').toLocaleString()}
                  </span>
                </div>
                <p className="mt-1 text-sm leading-relaxed text-slate-600">{h.changes_summary}</p>
                <p className="mt-0.5 text-xs font-semibold text-slate-400">
                  by {h.changed_by || 'system'}
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}