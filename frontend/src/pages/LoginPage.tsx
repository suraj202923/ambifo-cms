import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { Loader2, Lock, LogIn, ShieldCheck, User as UserIcon } from 'lucide-react'
import { useAuth } from '../auth'

export default function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    if (!username.trim() || !password) return
    setBusy(true)
    setError(null)
    try {
      await login(username, password)
      navigate('/', { replace: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="ambiflow-hero relative flex min-h-screen flex-col items-center justify-center p-4">
      <div className="dot-grid" />
      <div className="glow-orb h-72 w-72 animate-float bg-brand-cyan/25" style={{ top: '8%', left: '12%' }} />
      <div className="glow-orb h-72 w-72 animate-float bg-brand-teal/25" style={{ bottom: '8%', right: '12%', animationDelay: '-3s' }} />
      <div className="glow-orb h-56 w-56 animate-pulse-slow bg-brand-cyan/15" style={{ bottom: '25%', left: '38%' }} />

      <div className="relative z-10 w-full max-w-md">
        <div className="scroll-fade rounded-3xl bg-white p-8 shadow-2xl shadow-black/30 sm:p-10">
          <div className="mb-8 text-center">
            <img
              src="/ambifo-logo.png"
              alt="Ambifo"
              className="mx-auto h-auto w-52 select-none sm:w-60"
              draggable={false}
            />
            <div className="mt-5 flex items-center justify-center gap-3">
              <span className="h-px w-10 bg-slate-200" />
              <span className="font-display text-[11px] font-bold uppercase tracking-[0.2em] text-brand-teal">
                Cloud CRM
              </span>
              <span className="h-px w-10 bg-slate-200" />
            </div>
          </div>

          <h1 className="font-display text-xl font-bold text-navy-900">Welcome back</h1>
          <p className="mb-6 mt-1 text-sm text-slate-500">Sign in to continue to your dashboard</p>

          <form onSubmit={onSubmit}>
            <label className="mb-4 block">
              <span className="mb-1.5 block font-display text-xs font-bold uppercase tracking-widest text-navy-500">
                Username
              </span>
              <div className="relative">
                <UserIcon
                  size={16}
                  className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400"
                />
                <input
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  autoFocus
                  required
                  placeholder="Enter your username"
                  className="w-full rounded-xl border border-slate-300 bg-slate-50 py-3 pl-10 pr-4 text-sm text-navy-900 outline-none transition-all duration-200 placeholder:text-slate-400 focus:border-brand-teal focus:bg-white focus:ring-2 focus:ring-brand-teal/20"
                />
              </div>
            </label>

            <label className="mb-6 block">
              <span className="mb-1.5 block font-display text-xs font-bold uppercase tracking-widest text-navy-500">
                Password
              </span>
              <div className="relative">
                <Lock
                  size={16}
                  className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400"
                />
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  placeholder="Enter your password"
                  className="w-full rounded-xl border border-slate-300 bg-slate-50 py-3 pl-10 pr-4 text-sm text-navy-900 outline-none transition-all duration-200 placeholder:text-slate-400 focus:border-brand-teal focus:bg-white focus:ring-2 focus:ring-brand-teal/20"
                />
              </div>
            </label>

            {error && (
              <div className="mb-5 flex animate-fade-in items-center gap-2 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                <ShieldCheck size={14} className="shrink-0 text-red-500" />
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={busy}
              className="flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-brand-cyan to-brand-teal px-5 py-3.5 font-display text-sm font-bold text-navy-900 shadow-lg shadow-brand-teal/25 transition-all duration-300 hover:-translate-y-0.5 hover:shadow-xl hover:shadow-brand-teal/35 disabled:pointer-events-none disabled:opacity-60"
            >
              {busy ? <Loader2 size={16} className="animate-spin" /> : <LogIn size={16} />}
              {busy ? 'Signing in…' : 'Sign in to dashboard'}
            </button>
          </form>

          <p className="mt-6 text-center text-xs text-slate-400">
            Powered by React · Rust engine · FastAPI
          </p>
        </div>
      </div>
    </div>
  )
}