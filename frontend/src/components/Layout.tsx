import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import {
  Bot,
  CalendarClock,
  FileText,
  LayoutDashboard,
  Mail,
  Shapes,
  ShieldCheck,
  Target,
  Users,
  Settings,
  LogOut,
} from 'lucide-react'
import { useAuth } from '../auth'

const NAV_SECTIONS = [
  {
    label: 'Overview',
    items: [
      { to: '/', label: 'Dashboard', icon: LayoutDashboard },
      { to: '/customers', label: 'Opportunity', icon: Users },
      { to: '/leads', label: 'Leads', icon: Target },
    ],
  },
  {
    label: 'Engagement',
    items: [
      { to: '/email', label: 'Email', icon: Mail },
      { to: '/meetings', label: 'Meetings', icon: CalendarClock },
    ],
  },
  {
    label: 'Deliverables',
    items: [
      { to: '/documents', label: 'Documents', icon: FileText },
      { to: '/diagrams', label: 'Diagrams', icon: Shapes },
      { to: '/ai', label: 'AI Assistant', icon: Bot },
    ],
  },
]

const ADMIN_ITEMS = [
  { to: '/configuration', label: 'Configuration', icon: Settings },
  { to: '/admin', label: 'Admin', icon: ShieldCheck },
]

const ADMIN_SECTION = {
  label: 'System',
  items: ADMIN_ITEMS,
}

export default function Layout() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  function handleLogout() {
    logout()
    navigate('/login')
  }

  const visibleNav = [
    ...NAV_SECTIONS,
    ...(user?.is_admin ? [ADMIN_SECTION] : []),
  ]

  return (
    <div className="flex h-full">
      {/* ── Sidebar (desktop) ─────────────────────────────────── */}
      <aside className="relative hidden w-64 shrink-0 flex-col overflow-hidden bg-gradient-to-b from-teal-800 via-emerald-900 to-green-950 md:flex">
        {/* subtle deco */}
        <div className="pointer-events-none absolute -right-20 -top-20 h-48 w-48 rounded-full bg-emerald-300/10 blur-3xl" />
        <div className="pointer-events-none absolute -left-16 bottom-24 h-48 w-48 rounded-full bg-teal-300/10 blur-3xl" />
        <div className="dot-grid pointer-events-none absolute inset-0 opacity-[0.04]" />

        <div className="relative z-10 flex min-h-0 flex-1 flex-col">
          {/* logo */}
          <div className="shrink-0 p-5">
            <div className="flex items-center justify-between">
              <img
                src="/ambifo-logo.png"
                alt="Ambifo"
                className="h-20 w-auto select-none object-contain"
                draggable={false}
              />
              <span className="rounded-full border border-emerald-300/40 bg-emerald-300/10 px-2 py-0.5 font-display text-[9px] font-bold uppercase tracking-widest text-emerald-200">
                CRM v1
              </span>
            </div>
            <span className="mt-4 block h-px bg-gradient-to-r from-transparent via-white/15 to-transparent" />
          </div>

          {/* nav (scrollable) */}
          <nav className="min-h-0 flex-1 overflow-y-auto px-5 pb-4 custom-scroll">
            <div className="flex flex-col gap-5">
              {visibleNav.map((section) => (
                <div key={section.label}>
                  <p className="mb-1.5 px-3 font-display text-[10px] font-bold uppercase tracking-[0.2em] text-emerald-200/50">
                    {section.label}
                  </p>
                  <ul className="flex flex-col gap-1">
                    {section.items.map((item) => (
                      <li key={item.to}>
                        <NavLink
                          to={item.to}
                          end={item.to === '/'}
                          className={({ isActive }) =>
                            `group relative flex items-center gap-3 rounded-lg px-3 py-2.5 font-display text-sm font-semibold transition-all duration-300 ${
                              isActive
                                ? 'bg-gradient-to-r from-teal-400/25 to-emerald-300/10 text-white shadow-inner shadow-black/20 ring-1 ring-emerald-200/20'
                                : 'text-emerald-100/60 hover:bg-white/5 hover:text-white'
                            }`
                          }
                        >
                          {({ isActive }) => (
                            <>
                              {isActive && (
                                <span className="absolute left-0 top-1/2 h-5 w-1 -translate-y-1/2 rounded-r-full bg-gradient-to-b from-emerald-200 to-teal-400" />
                              )}
                              <item.icon
                                size={17}
                                className={`transition-all duration-300 ${
                                  isActive
                                    ? 'text-emerald-200 group-hover:scale-110'
                                    : 'text-emerald-100/40 group-hover:scale-110 group-hover:text-emerald-200'
                                }`}
                              />
                              {item.label}
                            </>
                          )}
                        </NavLink>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </nav>
        </div>

        {/* user card */}
        <div className="relative z-10 shrink-0 p-5">
          <div className="rounded-2xl border border-white/10 bg-white/[0.06] p-4 backdrop-blur-sm">
            <div className="flex items-center gap-3">
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-emerald-400 to-teal-500 font-display text-sm font-bold text-white shadow-lg shadow-green-950/40 ring-2 ring-white/20">
                {user?.username.slice(0, 1).toUpperCase()}
              </span>
              <div className="min-w-0 leading-tight">
                <div className="truncate font-display text-sm font-semibold text-white">
                  {user?.full_name || user?.username}
                </div>
                <div className="truncate text-xs text-emerald-100/60">{user?.email}</div>
              </div>
            </div>
            <button
              onClick={handleLogout}
              className="mt-3 flex w-full items-center justify-center gap-2 rounded-lg bg-gradient-to-r from-brand-coral to-red-600 px-3 py-2 font-display text-xs font-bold text-white shadow-md shadow-red-900/20 transition-all duration-300 hover:-translate-y-0.5 hover:shadow-lg hover:shadow-red-900/30"
            >
              <LogOut size={14} /> Sign out
            </button>
          </div>
        </div>
      </aside>

      <div className="flex flex-1 flex-col min-w-0">
        {/* mobile header */}
        <header className="ambiflow-hero flex items-center justify-between p-4 md:hidden">
          <div className="flex items-center gap-2">
            <img
              src="/ambifo-logo.png"
              alt="Ambifo"
              className="h-11 w-auto select-none object-contain"
              draggable={false}
            />
          </div>
          <div className="flex items-center gap-3">
            <span className="text-sm font-semibold text-white">{user?.username}</span>
            <button onClick={handleLogout} className="text-brand-cyan">
              <LogOut size={18} />
            </button>
          </div>
        </header>
        <nav className="flex gap-1 border-b border-slate-200 bg-white/80 p-2 backdrop-blur md:hidden">
          {NAV_SECTIONS.flatMap((s) => s.items).map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/'}
              className={({ isActive }) =>
                `flex flex-1 items-center justify-center gap-2 rounded-lg px-3 py-2 font-display text-xs font-semibold transition-colors ${
                  isActive
                    ? 'bg-navy-900 text-white'
                    : 'text-slate-600 hover:bg-slate-100'
                }`
              }
            >
              <item.icon size={14} /> {item.label}
            </NavLink>
          ))}
        </nav>

        <header className="sticky top-0 z-20 flex items-center justify-between border-b border-slate-200 bg-white/80 px-4 py-2.5 backdrop-blur sm:px-6 lg:px-8">
          <div className="font-display text-sm font-semibold text-slate-500">
            Welcome back, <span className="text-navy-900">{user?.full_name || user?.username}</span>
          </div>
        </header>

        <main className="min-h-0 flex-1 overflow-y-auto px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
          <div className="mx-auto w-full max-w-6xl">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  )
}