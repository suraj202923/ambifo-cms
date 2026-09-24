import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  CheckCircle2,
  KeyRound,
  Pencil,
  Plus,
  RefreshCcw,
  Search,
  Shield,
  ShieldCheck,
  UserCog,
  UserPlus,
  Users,
  X,
} from 'lucide-react'
import { adminApi } from '../api'
import type { User } from '../api/types'
import { useAuth } from '../auth'
import { Badge, Button, Field, inputCls, Panel, Spinner } from '../components/ui'

export default function AdminPage() {
  const queryClient = useQueryClient()
  const { user: me } = useAuth()
  const users = useQuery({ queryKey: ['admin-users'], queryFn: () => adminApi.users() })

  const [showCreate, setShowCreate] = useState(false)
  const [edit, setEdit] = useState<User | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [form, setForm] = useState({
    username: '',
    email: '',
    password: '',
    full_name: '',
    is_admin: false,
  })
  const [editForm, setEditForm] = useState({ full_name: '', email: '', is_admin: false, new_password: '' })
  const [resetAllPassword, setResetAllPassword] = useState('')

  const createMutation = useMutation({
    mutationFn: () =>
      adminApi.createUser({
        username: form.username,
        email: form.email,
        password: form.password,
        full_name: form.full_name || null,
        is_admin: form.is_admin,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin-users'] })
      setShowCreate(false)
      setForm({ username: '', email: '', password: '', full_name: '', is_admin: false })
    },
    onError: (e) => setError(e instanceof Error ? e.message : 'Create failed'),
  })

  const updateMutation = useMutation({
    mutationFn: (payload: { id: number } & Parameters<typeof adminApi.updateUser>[1]) =>
      adminApi.updateUser(payload.id, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin-users'] })
      setEdit(null)
    },
    onError: (e) => setError(e instanceof Error ? e.message : 'Update failed'),
  })

  const resetAllMutation = useMutation({
    mutationFn: () => adminApi.resetAllPasswords(resetAllPassword),
    onSuccess: (res) => {
      setResetAllPassword('')
      setError(null)
      window.alert(`Password reset for ${res.updated} active user(s)`)
    },
    onError: (e) => setError(e instanceof Error ? e.message : 'Reset failed'),
  })

  function toggleActive(u: User, active: boolean) {
    setError(null)
    updateMutation.mutate({ id: u.id, is_active: active })
  }

  function deleteUser(u: User) {
    if (!window.confirm(`Deactivate user '${u.username}'? This cannot be done to your own account.`)) return
    setError(null)
    updateMutation.mutate({ id: u.id, is_active: false })
  }

  const stats = useMemo(() => {
    const d = users.data ?? []
    return {
      total: d.length,
      admins: d.filter((u) => u.is_admin).length,
      active: d.filter((u) => u.is_active).length,
    }
  }, [users.data])

  const list = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return users.data ?? []
    return (users.data ?? []).filter(
      (u) =>
        u.username.toLowerCase().includes(q) ||
        u.email.toLowerCase().includes(q) ||
        (u.full_name ?? '').toLowerCase().includes(q),
    )
  }, [users.data, search])

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
              <ShieldCheck size={16} className="text-brand-cyan" />
              <span className="font-display text-[11px] font-bold uppercase tracking-[0.25em] text-brand-cyan">
                Ambifo CRM · Security
              </span>
            </div>
            <h1 className="mt-2 font-display text-2xl font-bold text-white sm:text-3xl">Admin Center</h1>
            <p className="mt-1.5 text-sm text-slate-400">Manage team members, roles and account security.</p>
          </div>

          <div className="flex items-center gap-3">
            <div className="flex flex-col items-center rounded-2xl border border-white/10 bg-white/5 px-6 py-4 backdrop-blur-sm transition-colors hover:border-brand-cyan/40">
              <span className="font-display text-2xl font-bold text-white">{stats.total}</span>
              <span className="mt-0.5 font-display text-[10px] font-semibold uppercase tracking-widest text-brand-cyan">
                Users
              </span>
            </div>
            <div className="hidden flex-col items-center rounded-2xl border border-emerald-400/25 bg-emerald-500/10 px-6 py-4 backdrop-blur-sm transition-colors hover:border-emerald-400/50 sm:flex">
              <span className="font-display text-2xl font-bold text-emerald-300">{stats.admins}</span>
              <span className="mt-0.5 font-display text-[10px] font-semibold uppercase tracking-widest text-emerald-400">
                Admins
              </span>
            </div>
            <div className="hidden flex-col items-center rounded-2xl border border-slate-400/25 bg-slate-500/10 px-6 py-4 backdrop-blur-sm transition-colors hover:border-slate-400/50 sm:flex">
              <span className="font-display text-2xl font-bold text-slate-100">{stats.active}</span>
              <span className="mt-0.5 font-display text-[10px] font-semibold uppercase tracking-widest text-slate-300">
                Active
              </span>
            </div>
          </div>
        </div>
      </section>

      {/* ── Body ─────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Users list */}
        <Panel className="scroll-fade h-fit lg:col-span-1">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="flex items-center gap-2 font-display text-sm font-bold tracking-wide text-navy-900 uppercase">
              <Users size={15} className="text-brand-teal" /> Users
            </h2>
            <Badge tone="teal">{list.length}</Badge>
          </div>

          <div className="relative mb-4">
            <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              className={`${inputCls} pl-9`}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search users…"
            />
          </div>

          {users.isLoading ? (
            <Spinner label="Loading users" />
          ) : list.length === 0 ? (
            <div className="py-10 text-center text-sm text-slate-400">No users found</div>
          ) : (
            <div className="space-y-3">
              {list.map((u) => (
                <div
                  key={u.id}
                  className="group rounded-2xl border border-slate-200 bg-white p-4 shadow-sm transition-all duration-300 hover:-translate-y-0.5 hover:border-brand-teal/30 hover:shadow-lg"
                >
                  <div className="flex items-center justify-between gap-3">
                    <div className="flex min-w-0 items-center gap-3">
                      <span
                        className={`grid h-11 w-11 shrink-0 place-items-center rounded-2xl font-display text-sm font-bold text-white shadow-md ${
                          u.is_admin
                            ? 'bg-gradient-to-br from-brand-teal to-brand-cyan shadow-brand-teal/40'
                            : 'bg-gradient-to-br from-slate-400 to-slate-500 shadow-slate-400/30'
                        }`}
                      >
                        {u.username.slice(0, 2).toUpperCase()}
                      </span>
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="truncate font-display text-sm font-bold text-navy-900">{u.username}</span>
                          {u.id === me?.id && <Badge tone="navy">you</Badge>}
                        </div>
                        <div className="truncate text-xs text-slate-400">
                          {u.email}
                          {u.full_name ? ` · ${u.full_name}` : ''}
                        </div>
                      </div>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <Badge tone={u.is_admin ? 'teal' : 'neutral'}>{u.is_admin ? 'Admin' : 'User'}</Badge>
                      <span
                        className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-semibold ${
                          u.is_active
                            ? 'border-green-200 bg-green-100 text-green-700'
                            : 'border-slate-200 bg-slate-100 text-slate-500'
                        }`}
                      >
                        <span className={`h-1.5 w-1.5 rounded-full ${u.is_active ? 'bg-green-500' : 'bg-slate-400'}`} />
                        {u.is_active ? 'Active' : 'Off'}
                      </span>
                    </div>
                  </div>

                  <div className="mt-3 flex items-center justify-end gap-1.5 border-t border-slate-100 pt-3">
                    <button
                      className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs font-semibold text-slate-500 transition-colors hover:border-brand-teal/40 hover:bg-brand-teal/5 hover:text-brand-teal-dark"
                      onClick={() => {
                        setEdit(u)
                        setEditForm({ full_name: u.full_name ?? '', email: u.email, is_admin: u.is_admin, new_password: '' })
                      }}
                    >
                      <Pencil size={12} /> Edit
                    </button>
                    <button
                      className={`inline-flex items-center rounded-lg border px-2.5 py-1.5 text-xs font-semibold transition-colors ${
                        u.is_active
                          ? 'border-slate-200 text-slate-500 hover:border-red-300 hover:bg-red-50 hover:text-red-600'
                          : 'border-brand-teal/30 text-brand-teal-dark hover:bg-brand-teal hover:text-white'
                      }`}
                      onClick={() => (u.is_active ? deleteUser(u) : toggleActive(u, true))}
                    >
                      {u.is_active ? 'Deactivate' : 'Activate'}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Panel>

        {/* Admin actions */}
        <Panel className="scroll-fade lg:col-span-2" style={{ animationDelay: '0.1s' }}>
          <div className="mb-5 flex items-center justify-between">
            <h2 className="flex items-center gap-2 font-display text-sm font-bold tracking-wide text-navy-900 uppercase">
              <Shield size={15} className="text-brand-teal" /> Administrator actions
            </h2>
            {!showCreate && (
              <Button icon={<Plus size={15} />} onClick={() => setShowCreate(true)}>
                Add user
              </Button>
            )}
          </div>

          {showCreate && (
            <div className="mb-6 overflow-hidden rounded-2xl border border-brand-teal/25 shadow-lg shadow-brand-teal/10">
              <div className="ambiflow-hero relative px-5 py-4">
                <div className="dot-grid" />
                <div className="relative z-10 flex items-center gap-3">
                  <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-brand-cyan to-brand-teal font-display text-white shadow-lg shadow-brand-cyan/30 ring-2 ring-white/20">
                    <UserPlus size={18} />
                  </span>
                  <div>
                    <h3 className="font-display text-base font-bold text-white">Add a new user</h3>
                    <p className="text-xs text-slate-300">Create an account and grant your team access</p>
                  </div>
                  <button
                    type="button"
                    className="ml-auto shrink-0 rounded-lg p-2 text-slate-300 transition-colors hover:bg-white/10 hover:text-white"
                    onClick={() => setShowCreate(false)}
                  >
                    <X size={18} />
                  </button>
                </div>
              </div>
              <form
                className="grid grid-cols-1 gap-4 p-5 sm:grid-cols-2"
                onSubmit={(e) => {
                  e.preventDefault()
                  setError(null)
                  createMutation.mutate()
                }}
              >
                <Field label="Username *">
                  <input className={inputCls} required value={form.username} onChange={(e) => setForm((f) => ({ ...f, username: e.target.value }))} />
                </Field>
                <Field label="Email *">
                  <input className={inputCls} required type="email" value={form.email} onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))} />
                </Field>
                <Field label="Full name">
                  <input className={inputCls} value={form.full_name} onChange={(e) => setForm((f) => ({ ...f, full_name: e.target.value }))} />
                </Field>
                <Field label="Password *">
                  <input className={inputCls} required minLength={6} type="password" value={form.password} onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))} />
                </Field>
                <label className="flex items-center gap-2 rounded-xl border border-brand-teal/15 bg-brand-teal/5 px-3 py-2.5 text-sm text-slate-600">
                  <input type="checkbox" checked={form.is_admin} onChange={(e) => setForm((f) => ({ ...f, is_admin: e.target.checked }))} className="h-4 w-4 accent-brand-teal" />
                  <ShieldCheck size={14} className="text-brand-teal" /> Grant admin (role) rights
                </label>
                <div className="flex items-end gap-2">
                  <Button type="submit" disabled={createMutation.isPending}>
                    {createMutation.isPending ? 'Creating…' : 'Create user'}
                  </Button>
                  <Button variant="ghost" onClick={() => setShowCreate(false)}>
                    Cancel
                  </Button>
                </div>
              </form>
            </div>
          )}

          {edit && (
            <div className="mb-6 overflow-hidden rounded-2xl border border-violet-300/60 shadow-lg shadow-violet-500/10">
              <div className="bg-gradient-to-r from-violet-600 to-indigo-600 px-5 py-4">
                <div className="flex items-center gap-3">
                  <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-white/15 font-display text-white ring-2 ring-white/20">
                    <UserCog size={18} />
                  </span>
                  <div>
                    <h3 className="font-display text-base font-bold text-white">Edit {edit.username}</h3>
                    <p className="text-xs text-violet-200">Update profile, role and password</p>
                  </div>
                  <button
                    type="button"
                    className="ml-auto shrink-0 rounded-lg p-2 text-violet-200 transition-colors hover:bg-white/10 hover:text-white"
                    onClick={() => setEdit(null)}
                  >
                    <X size={18} />
                  </button>
                </div>
              </div>
              <form
                className="grid grid-cols-1 gap-4 p-5 sm:grid-cols-2"
                onSubmit={(e) => {
                  e.preventDefault()
                  setError(null)
                  const payload: Parameters<typeof adminApi.updateUser>[1] = {
                    full_name: editForm.full_name || null,
                    email: editForm.email,
                    is_admin: editForm.is_admin,
                  }
                  if (editForm.new_password) payload.new_password = editForm.new_password
                  updateMutation.mutate({ id: edit.id, ...payload })
                }}
              >
                <Field label="Username">
                  <input className={`${inputCls} bg-slate-100`} value={edit.username} disabled readOnly />
                </Field>
                <Field label="Email *">
                  <input className={inputCls} required type="email" value={editForm.email} onChange={(e) => setEditForm((f) => ({ ...f, email: e.target.value }))} />
                </Field>
                <Field label="Full name">
                  <input className={inputCls} value={editForm.full_name} onChange={(e) => setEditForm((f) => ({ ...f, full_name: e.target.value }))} />
                </Field>
                <Field label="New password (leave blank to keep)">
                  <input className={inputCls} minLength={6} type="password" value={editForm.new_password} onChange={(e) => setEditForm((f) => ({ ...f, new_password: e.target.value }))} />
                </Field>
                <label className="flex items-center gap-2 rounded-xl border border-brand-teal/15 bg-brand-teal/5 px-3 py-2.5 text-sm text-slate-600">
                  <input type="checkbox" checked={editForm.is_admin} onChange={(e) => setEditForm((f) => ({ ...f, is_admin: e.target.checked }))} className="h-4 w-4 accent-brand-teal" />
                  <ShieldCheck size={14} className="text-brand-teal" /> Grant admin (role) rights
                </label>
                <div className="flex items-end gap-2">
                  <Button type="submit" disabled={updateMutation.isPending}>
                    {updateMutation.isPending ? 'Saving…' : 'Save changes'}
                  </Button>
                  <Button variant="ghost" onClick={() => setEdit(null)}>
                    Cancel
                  </Button>
                </div>
              </form>
            </div>
          )}

          <div className="rounded-2xl border border-amber-200 bg-gradient-to-br from-amber-50 to-orange-50 p-5">
            <div className="flex items-center gap-3">
              <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-amber-400 to-orange-500 text-white shadow-md shadow-amber-500/40">
                <KeyRound size={17} />
              </span>
              <div>
                <div className="font-display text-sm font-bold text-navy-900">Reset every active user's password</div>
                <p className="mt-0.5 text-xs text-slate-500">
                  Sets a single shared password for all active accounts — emergency recovery only.
                </p>
              </div>
            </div>
            <div className="mt-4 flex flex-col gap-2 sm:flex-row">
              <input
                className={`${inputCls} sm:max-w-72`}
                type="password"
                minLength={6}
                value={resetAllPassword}
                onChange={(e) => setResetAllPassword(e.target.value)}
                placeholder="New shared password…"
              />
              <Button
                variant="secondary"
                disabled={resetAllMutation.isPending || resetAllPassword.length < 6}
                onClick={() => resetAllMutation.mutate()}
              >
                <RefreshCcw size={15} /> Reset all
              </Button>
            </div>
          </div>

          {error && (
            <div className="mt-4 flex items-center gap-2 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-600">
              <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-red-100">
                <X size={13} className="text-red-600" />
              </span>
              {error}
            </div>
          )}

          <div className="mt-5 flex items-center gap-2 rounded-xl border border-slate-100 bg-slate-50/60 px-4 py-3 text-xs text-slate-400">
            <CheckCircle2 size={14} className="shrink-0 text-brand-teal" />
            Roles are enforced across all pages — admins can manage configuration and users.
          </div>
        </Panel>
      </div>
    </div>
  )
}