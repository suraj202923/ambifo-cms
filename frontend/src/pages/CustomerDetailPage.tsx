import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import {
  ArrowLeft,
  Banknote,
  Briefcase,
  Building2,
  Calculator,
  CalendarClock,
  Cloud,
  CreditCard,
  Download,
  ExternalLink,
  Eye,
  FileArchive,
  FileImage,
  FilePlus2,
  FileSpreadsheet,
  FileText,
  Film,
  FolderUp,
  Globe,
  Info,
  Mail,
  MapPin,
  MessageSquareText,
  Pencil,
  Phone,
  Tag,
  Trash2,
  UserCheck,
  Users,
  X,
} from 'lucide-react'
import { customerApi, documentApi } from '../api'
import type { CustomerCreate } from '../api/types'
import {
  Badge,
  Button,
  EmptyState,
  Field,
  FilePreviewModal,
  inputCls,
  isTextPreview,
  PageLoading,
  Panel,
  PanelTitle,
  selectCls,
  Spinner,
} from '../components/ui'

type Tab = 'details' | 'documents' | 'financials'

export default function CustomerDetailPage() {
  const { id } = useParams()
  const customerId = Number(id)
  const queryClient = useQueryClient()
  const [tab, setTab] = useState<Tab>('details')
  const [editing, setEditing] = useState(false)
  const [form, setForm] = useState<CustomerCreate | null>(null)
  const [formError, setFormError] = useState<string | null>(null)

  const { data: customer, isLoading, isError } = useQuery({
    queryKey: ['customer', customerId],
    queryFn: () => customerApi.get(customerId),
  })
  const { data: lookups } = useQuery({ queryKey: ['lookups'], queryFn: customerApi.lookups })

  const updateMutation = useMutation({
    mutationFn: (payload: CustomerCreate) => customerApi.update(customerId, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['customer', customerId] })
      queryClient.invalidateQueries({ queryKey: ['customers'] })
      queryClient.invalidateQueries({ queryKey: ['customer-stats'] })
      queryClient.invalidateQueries({ queryKey: ['dashboard'] })
      setEditing(false)
      setForm(null)
    },
    onError: (e) => setFormError(e instanceof Error ? e.message : 'Update failed'),
  })

  function openEdit() {
    if (!customer) return
    setForm({
      account_name: customer.account_name,
      customer_name: customer.customer_name,
      designation: customer.designation,
      email: customer.email,
      alternate_emails: customer.alternate_emails,
      phone: customer.phone,
      cloud: customer.cloud,
      main_page_address: customer.main_page_address,
      billing: customer.billing,
      city: customer.city,
      aws_id: customer.aws_id,
      aws_calculator_link: customer.aws_calculator_link,
      opportunity_id: customer.opportunity_id,
      segment: customer.segment,
      deal_status: customer.deal_status,
      comment: customer.comment,
      next_action_planned: customer.next_action_planned,
      assign_to_user_id: customer.assign_to_user_id,
    })
    setFormError(null)
    setEditing(true)
  }

  function setField<K extends keyof CustomerCreate>(key: K, value: CustomerCreate[K]) {
    setForm((f) => (f ? { ...f, [key]: value } : f))
  }

  if (isLoading) return <PageLoading label="Loading customer" />
  if (isError || !customer)
    return <div className="rounded-2xl border border-red-200 bg-red-50 p-6 text-red-600">Customer not found</div>

  const TABS: { key: Tab; label: string; icon: typeof Info }[] = [
    { key: 'details', label: 'Details', icon: Info },
    { key: 'documents', label: 'Documents', icon: FileText },
    { key: 'financials', label: 'Financials', icon: Banknote },
  ]

  return (
    <div>
      <Link
        to="/customers"
        className="mb-3 inline-flex items-center gap-1.5 font-display text-xs font-semibold text-slate-500 transition-colors hover:text-brand-teal-dark"
      >
        <ArrowLeft size={14} /> Back to opportunities
      </Link>

      <div className="ambiflow-hero relative mb-6 overflow-hidden rounded-3xl p-7 text-white sm:p-9">
        <div className="dot-grid opacity-15" />
        <div className="glow-orb h-40 w-40 animate-float bg-brand-cyan/25" style={{ top: '-40px', right: '5%' }} />
        <div className="glow-orb h-40 w-40 animate-pulse-slow bg-brand-teal/20" style={{ bottom: '-50px', right: '30%' }} />
        <div className="relative z-10 flex flex-wrap items-start justify-between gap-5">
          <div className="flex min-w-0 items-start gap-4">
            <span className="grid h-20 w-20 shrink-0 place-items-center rounded-3xl bg-gradient-to-br from-emerald-400 to-teal-500 font-display text-2xl font-bold text-white shadow-xl shadow-green-950/40 ring-2 ring-white/25">
              {(customer.customer_name.trim().split(/\s+/).map((w) => w[0]).join('').slice(0, 2) || '?').toUpperCase()}
            </span>
            <div className="min-w-0">
              <p className="flex items-center gap-2 font-display text-xs font-semibold tracking-widest text-brand-cyan uppercase">
                {customer.segment ?? 'Opportunity'}
                {customer.opportunity_id && (
                  <span className="rounded-full border border-white/15 bg-white/10 px-2 py-0.5 normal-case tracking-normal text-slate-200">
                    {customer.opportunity_id}
                  </span>
                )}
              </p>
              <h1 className="mt-1 break-words font-display text-3xl font-bold text-white">{customer.customer_name}</h1>
              <p className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-slate-300">
                {customer.account_name && <span>{customer.account_name}</span>}
                {customer.account_name && customer.city && <span className="text-slate-500">·</span>}
                {customer.city && (
                  <span className="inline-flex items-center gap-1">
                    <MapPin size={13} /> {customer.city}
                  </span>
                )}
                {customer.phone && (
                  <a className="inline-flex items-center gap-1 text-slate-300 transition-colors hover:text-white" href={`tel:${customer.phone}`}>
                    <Phone size={13} /> {customer.phone}
                  </a>
                )}
                {customer.email && (
                  <a className="inline-flex items-center gap-1 text-slate-300 transition-colors hover:text-white" href={`mailto:${customer.email}`}>
                    <Mail size={13} /> {customer.email}
                  </a>
                )}
              </p>
            </div>
          </div>
          <div className="flex flex-wrap items-center justify-end gap-2">
            {customer.deal_status && (
              <span className="rounded-full border border-brand-cyan/30 bg-brand-cyan/10 px-3 py-1 font-display text-xs font-bold text-brand-cyan backdrop-blur-sm">
                {customer.deal_status}
              </span>
            )}
            {customer.cloud && (
              <span className="rounded-full border border-white/15 bg-white/10 px-3 py-1 font-display text-xs font-semibold text-white backdrop-blur-sm">
                <Cloud size={11} className="mr-1 inline" /> {customer.cloud}
              </span>
            )}
            {(() => {
              const owner = lookups?.users.find((u) => u.id === customer.assign_to_user_id)
              return owner ? (
                <span className="rounded-full border border-brand-teal/40 bg-brand-teal/15 px-3 py-1 font-display text-xs font-semibold text-brand-teal backdrop-blur-sm">
                  {owner.username}
                </span>
              ) : null
            })()}
            <button
              onClick={openEdit}
              className="flex items-center gap-1.5 rounded-full border border-white/20 bg-white/10 px-4 py-1.5 font-display text-xs font-bold text-white backdrop-blur-sm transition-all duration-300 hover:bg-white/20"
            >
              <Pencil size={12} /> Edit
            </button>
          </div>
        </div>
      </div>

      <div className="scroll-fade mb-4 flex gap-1 rounded-2xl border border-slate-200 bg-white p-1 shadow-sm w-fit">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`flex items-center gap-2 rounded-xl px-4 py-2 font-display text-sm font-bold transition-all duration-300 ${
              tab === t.key
                ? 'bg-navy-900 text-white shadow-md'
                : 'text-slate-500 hover:bg-slate-100'
            }`}
          >
            <t.icon size={15} className={tab === t.key ? 'text-brand-cyan' : ''} />
            {t.label}
          </button>
        ))}
      </div>

      <div key={tab} className="animate-fade-in">
        {tab === 'details' && <DetailsTab customerId={customerId} />}
        {tab === 'documents' && <DocumentsTab customerId={customerId} />}
        {tab === 'financials' && <FinancialsTab customerId={customerId} />}
      </div>

      {editing && form && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-navy-900/60 p-4 backdrop-blur-sm"
          role="dialog"
          aria-modal="true"
          onClick={() => setEditing(false)}
        >
          <div
            className="scroll-fade max-h-[90vh] w-full max-w-4xl overflow-y-auto rounded-2xl border border-slate-200 bg-white shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="ambiflow-hero relative px-6 py-5 sm:px-8">
              <div className="relative z-10 flex items-center gap-4">
                <span className="grid h-12 w-12 shrink-0 place-items-center rounded-2xl bg-gradient-to-br from-emerald-400 to-teal-500 font-display font-bold text-white shadow-lg shadow-green-950/30 ring-2 ring-white/20">
                  {(customer.customer_name.trim().split(/\s+/).map((w) => w[0]).join('').slice(0, 2) || '?').toUpperCase()}
                </span>
                <div className="min-w-0">
                  <h2 className="font-display text-lg font-bold text-white">Edit customer</h2>
                  <p className="truncate text-sm text-emerald-100/70">{customer.customer_name}</p>
                </div>
                <button
                  type="button"
                  className="ml-auto shrink-0 rounded-lg p-2 text-emerald-100/70 transition-colors hover:bg-white/10 hover:text-white"
                  onClick={() => setEditing(false)}
                >
                  <X size={18} />
                </button>
              </div>
            </div>

            <form
              onSubmit={(e) => {
                e.preventDefault()
                setFormError(null)
                updateMutation.mutate(form)
              }}
              className="space-y-8 p-6 sm:p-8"
            >
              {/* contact */}
              <section>
                <div className="mb-3 flex items-center gap-2.5">
                  <span className="grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-brand-teal/10 text-brand-teal-dark">
                    <Users size={15} />
                  </span>
                  <div>
                    <h3 className="font-display text-sm font-bold text-navy-900">Contact details</h3>
                    <p className="text-[11px] text-slate-400">How to reach this customer</p>
                  </div>
                </div>
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
                  <Field label={<span>Customer name <span className="text-red-500">*</span></span>}>
                    <input className={inputCls} required value={form.customer_name} onChange={(e) => setField('customer_name', e.target.value)} placeholder="Acme Corp" />
                  </Field>
                  <Field label="Company / account">
                    <div className="relative">
                      <Building2 size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                      <input className={`${inputCls} pl-9`} value={form.account_name ?? ''} onChange={(e) => setField('account_name', e.target.value)} placeholder="Acme Inc." />
                    </div>
                  </Field>
                  <Field label="Designation">
                    <div className="relative">
                      <Briefcase size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                      <input className={`${inputCls} pl-9`} value={form.designation ?? ''} onChange={(e) => setField('designation', e.target.value)} placeholder="CTO / IT Manager" />
                    </div>
                  </Field>
                  <Field label={<span>Email <span className="text-red-500">*</span></span>}>
                    <div className="relative">
                      <Mail size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                      <input type="email" className={`${inputCls} pl-9`} required value={form.email} onChange={(e) => setField('email', e.target.value)} placeholder="name@company.com" />
                    </div>
                  </Field>
                  <Field label="Phone">
                    <div className="relative">
                      <Phone size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                      <input className={`${inputCls} pl-9`} value={form.phone ?? ''} onChange={(e) => setField('phone', e.target.value)} placeholder="+1 …" />
                    </div>
                  </Field>
                  <Field label="City">
                    <div className="relative">
                      <MapPin size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                      <input className={`${inputCls} pl-9`} value={form.city ?? ''} onChange={(e) => setField('city', e.target.value)} placeholder="Mumbai" />
                    </div>
                  </Field>
                  <Field label="Website URL" className="sm:col-span-2">
                    <div className="relative">
                      <Globe size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                      <input className={`${inputCls} pl-9`} value={form.main_page_address ?? ''} onChange={(e) => setField('main_page_address', e.target.value)} placeholder="https://www.acme.com" />
                    </div>
                  </Field>
                  <Field label="Alternate emails">
                    <input className={inputCls} value={form.alternate_emails ?? ''} onChange={(e) => setField('alternate_emails', e.target.value)} placeholder="first@x.com, second@x.com" />
                  </Field>
                </div>
              </section>

              {/* pipeline */}
              <section>
                <div className="mb-3 flex items-center gap-2.5">
                  <span className="grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-brand-teal/10 text-brand-teal-dark">
                    <Tag size={15} />
                  </span>
                  <div>
                    <h3 className="font-display text-sm font-bold text-navy-900">Pipeline</h3>
                    <p className="text-[11px] text-slate-400">Categorize and assign the opportunity</p>
                  </div>
                </div>
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
                  <Field label="Cloud operator">
                    <div className="relative">
                      <Cloud size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                      <input className={`${inputCls} pl-9`} list="cloud-ops" value={form.cloud ?? ''} onChange={(e) => setField('cloud', e.target.value)} placeholder="AWS / Azure / GCP" />
                    </div>
                    <datalist id="cloud-ops">
                      {lookups?.cloud_operators.map((c) => <option key={c.id} value={c.name} />)}
                    </datalist>
                  </Field>
                  <Field label="Segment">
                    <select className={selectCls} value={form.segment ?? ''} onChange={(e) => setField('segment', e.target.value)}>
                      <option value="">— select —</option>
                      {lookups?.segments.map((s) => <option key={s.id} value={s.name}>{s.name}</option>)}
                    </select>
                  </Field>
                  <Field label="Deal status">
                    <select className={selectCls} value={form.deal_status ?? ''} onChange={(e) => setField('deal_status', e.target.value)}>
                      <option value="">— select —</option>
                      {lookups?.statuses.map((s) => <option key={s.id} value={s.name}>{s.name}</option>)}
                    </select>
                    {lookups && lookups.statuses.length > 0 && (
                      <div className="mt-1.5 flex flex-wrap items-center gap-2">
                        {lookups.statuses.map((s) => (
                          <span key={s.id} className="inline-flex items-center gap-1 text-[10px] font-medium text-slate-400">
                            <span className="h-2 w-2 rounded-full" style={{ backgroundColor: s.color || '#94a3b8' }} /> {s.name}
                          </span>
                        ))}
                      </div>
                    )}
                  </Field>
                  <Field label="Assigned to">
                    <div className="relative">
                      <UserCheck size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                      <select className={`${selectCls} pl-9`} value={form.assign_to_user_id ?? ''} onChange={(e) => setField('assign_to_user_id', e.target.value ? Number(e.target.value) : null)}>
                        <option value="">Unassigned</option>
                        {lookups?.users.map((u) => <option key={u.id} value={u.id}>{u.username}</option>)}
                      </select>
                    </div>
                  </Field>
                  <Field label="Opportunity ID">
                    <div className="relative">
                      <FileText size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                      <input className={`${inputCls} pl-9`} value={form.opportunity_id ?? ''} onChange={(e) => setField('opportunity_id', e.target.value)} placeholder="OPP-2026-001" />
                    </div>
                  </Field>
                  <Field label="Next action planned" className="lg:col-span-2">
                    <div className="relative">
                      <CalendarClock size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                      <input className={`${inputCls} pl-9`} value={form.next_action_planned ?? ''} onChange={(e) => setField('next_action_planned', e.target.value)} placeholder="Follow-up call on…" />
                    </div>
                  </Field>
                </div>
              </section>

              {/* aws & billing */}
              <section className="rounded-2xl border border-amber-200/70 bg-gradient-to-br from-amber-50/70 to-orange-50/50 p-5">
                <div className="mb-3 flex items-center gap-2.5">
                  <span className="grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-amber-500/15 text-amber-600">
                    <CreditCard size={15} />
                  </span>
                  <div>
                    <h3 className="font-display text-sm font-bold text-navy-900">AWS &amp; billing</h3>
                    <p className="text-[11px] text-slate-400">Cloud account references and commercial details</p>
                  </div>
                </div>
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
                  <Field label="AWS ID">
                    <div className="relative">
                      <Cloud size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                      <input className={`${inputCls} pl-9`} value={form.aws_id ?? ''} onChange={(e) => setField('aws_id', e.target.value)} placeholder="acc-12345" />
                    </div>
                  </Field>
                  <Field label="AWS calculator link">
                    <div className="flex gap-1.5">
                      <input className={inputCls} value={form.aws_calculator_link ?? ''} onChange={(e) => setField('aws_calculator_link', e.target.value)} placeholder="https://calculator.aws/…" />
                      <a
                        href="https://calculator.aws"
                        target="_blank"
                        rel="noopener noreferrer"
                        title="Open AWS Pricing Calculator"
                        className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-amber-300/60 bg-white text-amber-600 transition-colors hover:bg-amber-500 hover:text-white"
                      >
                        <Calculator size={15} />
                      </a>
                    </div>
                  </Field>
                  <Field label="Billing">
                    <div className="relative">
                      <CreditCard size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                      <input className={`${inputCls} pl-9`} value={form.billing ?? ''} onChange={(e) => setField('billing', e.target.value)} placeholder="Invoice / PO details" />
                    </div>
                  </Field>
                </div>
              </section>

              {/* notes */}
              <section>
                <div className="mb-3 flex items-center gap-2.5">
                  <span className="grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-brand-teal/10 text-brand-teal-dark">
                    <MessageSquareText size={15} />
                  </span>
                  <div>
                    <h3 className="font-display text-sm font-bold text-navy-900">Notes</h3>
                    <p className="text-[11px] text-slate-400">Internal context for the team</p>
                  </div>
                </div>
                <Field label="Comment">
                  <textarea
                    className={`${inputCls} min-h-[90px] resize-y`}
                    value={form.comment ?? ''}
                    onChange={(e) => setField('comment', e.target.value)}
                    placeholder="Internal notes about this opportunity"
                  />
                </Field>
              </section>

              {formError && <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-600">{formError}</div>}

              <div className="flex items-center justify-end gap-2 border-t border-slate-100 pt-5">
                <span className="mr-auto text-xs text-slate-400">Fields marked <span className="text-red-500">*</span> are required</span>
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => setEditing(false)}
                >
                  Cancel
                </Button>
                <Button disabled={updateMutation.isPending} type="submit">
                  {updateMutation.isPending ? 'Saving…' : 'Save changes'}
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}

function DetailsTab({ customerId }: { customerId: number }) {
  const { data: customer } = useQuery({
    queryKey: ['customer', customerId],
    queryFn: () => customerApi.get(customerId),
  })
  const { data: lookups } = useQuery({ queryKey: ['lookups'], queryFn: customerApi.lookups })

  if (!customer) return null

  const assignee = lookups?.users.find((u) => u.id === customer.assign_to_user_id)
  const statusColor = lookups?.statuses.find((s) => s.name === customer.deal_status)?.color ?? '#94a3b8'

  function Row({ icon: Icon, label, children }: { icon: typeof Info; label: string; children: ReactNode }) {
    return (
      <div className="rounded-xl border border-slate-100 bg-slate-50/60 px-3.5 py-3 transition-colors hover:border-brand-teal/30 hover:bg-white">
        <div className="mb-1 flex items-center gap-1.5 font-display text-[10px] font-bold tracking-widest text-slate-500 uppercase">
          <Icon size={11} className="text-brand-teal" /> {label}
        </div>
        <div className="break-words text-sm text-slate-800">{children}</div>
      </div>
    )
  }

  function Sec({ icon: Icon, title, sub, children }: { icon: typeof Info; title: string; sub: string; children: ReactNode }) {
    return (
      <section>
        <div className="mb-3 flex items-center gap-2.5">
          <span className="grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-brand-teal/10 text-brand-teal-dark">
            <Icon size={15} />
          </span>
          <div>
            <h3 className="font-display text-sm font-bold text-navy-900">{title}</h3>
            <p className="text-[11px] text-slate-400">{sub}</p>
          </div>
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">{children}</div>
      </section>
    )
  }

  return (
    <Panel>
      <div className="space-y-8">
        <Sec icon={Users} title="Contact details" sub="How to reach this customer">
          <Row icon={Users} label="Customer name">{customer.customer_name}</Row>
          <Row icon={Building2} label="Company / account">{customer.account_name ?? '—'}</Row>
          <Row icon={Briefcase} label="Designation">{customer.designation ?? '—'}</Row>
          <Row icon={Mail} label="Email">
            {customer.email ? (
              <a className="font-medium text-brand-teal-dark hover:underline" href={`mailto:${customer.email}`}>{customer.email}</a>
            ) : '—'}
          </Row>
          <Row icon={FileSpreadsheet} label="Alternate emails">
            {customer.alternate_emails ? (
              <a className="text-brand-teal-dark hover:underline" href={`mailto:${customer.alternate_emails}`}>{customer.alternate_emails}</a>
            ) : '—'}
          </Row>
          <Row icon={Phone} label="Phone">
            {customer.phone ? (
              <a className="font-medium text-brand-teal-dark hover:underline" href={`tel:${customer.phone}`}>{customer.phone}</a>
            ) : '—'}
          </Row>
          <Row icon={MapPin} label="City">{customer.city ?? '—'}</Row>
          <Row icon={Globe} label="Website">
            {customer.main_page_address ? (
              <a className="inline-flex items-center gap-1 font-medium text-brand-teal-dark hover:underline" href={customer.main_page_address} target="_blank" rel="noopener noreferrer">
                {customer.main_page_address} <ExternalLink size={12} />
              </a>
            ) : '—'}
          </Row>
        </Sec>

        <Sec icon={Tag} title="Pipeline" sub="Categorization and ownership">
          <Row icon={Cloud} label="Cloud operator">{customer.cloud ?? '—'}</Row>
          <Row icon={Tag} label="Segment">{customer.segment ?? '—'}</Row>
          <Row icon={Info} label="Deal status">
            {customer.deal_status ? (
              <span className="inline-flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full" style={{ background: statusColor }} />
                <span className="font-semibold">{customer.deal_status}</span>
              </span>
            ) : '—'}
          </Row>
          <Row icon={UserCheck} label="Assigned to">{assignee?.username ?? 'Unassigned'}</Row>
          <Row icon={FileText} label="Opportunity ID">{customer.opportunity_id ?? '—'}</Row>
          <Row icon={CalendarClock} label="Next action planned">{customer.next_action_planned ?? '—'}</Row>
        </Sec>

        <section className="rounded-2xl border border-amber-200/70 bg-gradient-to-br from-amber-50/70 to-orange-50/50 p-5">
          <div className="mb-3 flex items-center gap-2.5">
            <span className="grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-amber-500/15 text-amber-600">
              <CreditCard size={15} />
            </span>
            <div>
              <h3 className="font-display text-sm font-bold text-navy-900">AWS &amp; billing</h3>
              <p className="text-[11px] text-slate-400">Cloud account references and commercial details</p>
            </div>
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <Row icon={Cloud} label="AWS ID">{customer.aws_id ?? '—'}</Row>
            <Row icon={Calculator} label="AWS calculator link">
              {customer.aws_calculator_link ? (
                <a className="inline-flex max-w-full items-center gap-1 truncate font-medium text-amber-700 hover:underline" href={customer.aws_calculator_link} target="_blank" rel="noopener noreferrer">
                  Open calculator <ExternalLink size={12} className="shrink-0" />
                </a>
              ) : '—'}
            </Row>
            <Row icon={CreditCard} label="Billing">{customer.billing ?? '—'}</Row>
          </div>
        </section>

        {customer.comment && (
          <section>
            <div className="mb-3 flex items-center gap-2.5">
              <span className="grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-brand-teal/10 text-brand-teal-dark">
                <MessageSquareText size={15} />
              </span>
              <div>
                <h3 className="font-display text-sm font-bold text-navy-900">Notes</h3>
                <p className="text-[11px] text-slate-400">Internal context for the team</p>
              </div>
            </div>
            <div className="rounded-xl border border-slate-200 bg-slate-50/60 p-4 text-sm leading-relaxed text-slate-700">{customer.comment}</div>
          </section>
        )}

        <div className="flex flex-wrap gap-x-8 gap-y-2 border-t border-slate-100 pt-4 text-xs text-slate-400">
          <span>Created <span className="font-semibold text-slate-600">{new Date(customer.created_at).toLocaleString()}</span></span>
          <span>Updated <span className="font-semibold text-slate-600">{new Date(customer.updated_at).toLocaleString()}</span></span>
        </div>
      </div>
    </Panel>
  )
}

function formatRelative(iso: string): string {
  const d = new Date(iso)
  const diff = Date.now() - d.getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.floor(hrs / 24)
  if (days < 30) return `${days}d ago`
  return d.toLocaleDateString()
}

function formatBytes(bytes: number | null): string {
  if (bytes == null || bytes <= 0) return '—'
  const kb = bytes / 1024
  if (kb < 1024) return `${Math.round(kb)} KB`
  const mb = kb / 1024
  return `${mb.toFixed(1)} MB`
}

function fileMeta(name: string): { icon: typeof FileText; color: string; badge: string } {
  const ext = (name.split('.').pop() || '').toLowerCase()
  if (['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp', 'bmp'].includes(ext)) return { icon: FileImage, color: 'from-green-500 to-emerald-600', badge: 'image' }
  if (['mp4', 'mov', 'avi', 'mkv', 'webm'].includes(ext)) return { icon: Film, color: 'from-rose-500 to-pink-600', badge: 'video' }
  if (['pdf'].includes(ext)) return { icon: FileText, color: 'from-red-500 to-rose-600', badge: 'pdf' }
  if (['zip', 'rar', '7z', 'tar', 'gz'].includes(ext)) return { icon: FileArchive, color: 'from-amber-500 to-orange-600', badge: 'archive' }
  if (['xls', 'xlsx', 'csv', 'ods'].includes(ext)) return { icon: FileSpreadsheet, color: 'from-green-500 to-teal-600', badge: 'sheet' }
  if (['doc', 'docx', 'txt', 'md', 'rtf'].includes(ext)) return { icon: FileText, color: 'from-sky-500 to-blue-600', badge: 'doc' }
  return { icon: FileText, color: 'from-slate-500 to-slate-700', badge: ext || 'file' }
}

function DocumentsTab({ customerId }: { customerId: number }) {
  const queryClient = useQueryClient()
  const fileRef = useRef<HTMLInputElement>(null)

  const docs = useQuery({
    queryKey: ['customer-documents', customerId],
    queryFn: () => documentApi.list(customerId),
  })
  const sows = useQuery({
    queryKey: ['sows', customerId],
    queryFn: () => documentApi.sows(customerId),
  })

  const [description, setDescription] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [selectedSow, setSelectedSow] = useState<number | null>(null)
  const [preview, setPreview] = useState<{
    filename: string
    content?: string | null
    blobUrl?: string | null
    loading: boolean
    error?: string | null
  } | null>(null)

  const uploadMutation = useMutation({
    mutationFn: (file: File) => documentApi.upload(customerId, file, description || undefined),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['customer-documents'] })
      setDescription('')
      if (fileRef.current) fileRef.current.value = ''
    },
    onError: (e) => setError(e instanceof Error ? e.message : 'Upload failed'),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => documentApi.remove(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['customer-documents'] }),
  })

  const deleteSowMutation = useMutation({
    mutationFn: (id: number) => documentApi.deleteSow(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sows'] })
      setSelectedSow(null)
    },
  })

  const sendEmailMutation = useMutation({
    mutationFn: (id: number) => documentApi.sendSowEmail(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['email-logs'] }),
  })

  async function download(docId: number, filename: string) {
    try {
      const blob = await documentApi.download(docId)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Download failed')
    }
  }

  async function view(docId: number, filename: string, mimeType?: string | null) {
    setPreview({ filename, loading: true })
    try {
      const blob = await documentApi.download(docId)
      if (isTextPreview(filename, mimeType)) {
        const text = await blob.text()
        setPreview({ filename, content: text, loading: false })
      } else {
        const url = URL.createObjectURL(blob)
        setPreview({ filename, blobUrl: url, loading: false })
      }
    } catch (e) {
      setPreview({
        filename,
        loading: false,
        error: e instanceof Error ? e.message : 'Could not load preview',
      })
    }
  }

  async function downloadSow(sowId: number, filename: string) {
    try {
      const blob = await documentApi.downloadSow(sowId)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename || 'sow.docx'
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Download failed')
    }
  }

  return (
    <div className="space-y-6">
      <Panel className="scroll-fade">
        <PanelTitle><FolderUp size={15} className="text-brand-teal" /> Upload file</PanelTitle>
        <div className="flex flex-col gap-4 sm:flex-row sm:items-end">
          <div className="flex-1">
            <Field label="Description">
              <input
                className={inputCls}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="e.g. Signed SOW, invoice, architecture doc…"
              />
            </Field>
          </div>
          <input
            ref={fileRef}
            type="file"
            className="hidden"
            onChange={(e) => {
              setError(null)
              const f = e.target.files?.[0]
              if (f) uploadMutation.mutate(f)
            }}
          />
          <Button icon={<FolderUp size={15} />} disabled={uploadMutation.isPending} onClick={() => fileRef.current?.click()}>
            {uploadMutation.isPending ? 'Uploading…' : 'Choose file'}
          </Button>
        </div>
        {error && <div className="mt-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-600">⚠ {error}</div>}
      </Panel>

      <Panel className="scroll-fade">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <PanelTitle><FileText size={15} className="text-brand-teal" /> Stored files</PanelTitle>
          {docs.data && <Badge tone="teal">{docs.data.length} file{docs.data.length === 1 ? '' : 's'}</Badge>}
        </div>
        {docs.isLoading ? (
          <Spinner label="Loading files" />
        ) : docs.data?.length ? (
          <div className="space-y-2">
            {docs.data.map((d) => {
              const meta = fileMeta(d.original_filename)
              const Icon = meta.icon
              return (
                <div key={d.id} className="group flex items-center justify-between gap-3 rounded-xl border border-slate-200 px-4 py-3 transition-colors hover:border-brand-teal/30 hover:bg-slate-50/60">
                  <div className="flex min-w-0 items-center gap-3">
                    <span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br ${meta.color} text-white shadow-sm`}>
                      <Icon size={17} />
                    </span>
                    <div className="min-w-0">
                      <div className="truncate font-display text-sm font-semibold text-navy-900">{d.original_filename}</div>
                      {d.description && <div className="truncate text-xs text-slate-500">{d.description}</div>}
                      <div className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-xs text-slate-400">
                        <span>{formatBytes(d.file_size_bytes)}</span>
                        <span className="text-slate-300">·</span>
                        <span title={new Date(d.created_at).toLocaleString()}>{formatRelative(d.created_at)}</span>
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-1">
                    <Badge tone="neutral">{meta.badge}</Badge>
                    {d.blob_url && (
                      <a className="rounded-lg p-2 text-slate-400 transition-colors hover:bg-brand-teal/10 hover:text-brand-teal-dark" title="Open in OneDrive" href={d.blob_url} target="_blank" rel="noopener noreferrer">
                        <ExternalLink size={15} />
                      </a>
                    )}
                    <button className="rounded-lg p-2 text-slate-400 transition-colors hover:bg-brand-teal/10 hover:text-brand-teal-dark" title="View" onClick={() => view(d.id, d.original_filename, d.mime_type)}>
                      <Eye size={15} />
                    </button>
                    <button className="rounded-lg p-2 text-slate-400 transition-colors hover:bg-brand-teal/10 hover:text-brand-teal-dark" title="Download" onClick={() => download(d.id, d.original_filename)}>
                      <Download size={15} />
                    </button>
                    <button className="rounded-lg p-2 text-slate-400 transition-colors hover:bg-red-50 hover:text-red-500" title="Delete" onClick={() => { if (confirm('Delete this file?')) deleteMutation.mutate(d.id) }}>
                      <Trash2 size={14} />
                    </button>
                  </div>
                </div>
              )
            })}
          </div>
        ) : (
          <EmptyState message="No files stored for this opportunity yet" />
        )}
      </Panel>

      <Panel className="scroll-fade" style={{ animationDelay: '0.1s' }}>
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <PanelTitle><FilePlus2 size={15} className="text-brand-teal" /> SOW library</PanelTitle>
          {sows.data && <Badge tone="neutral">{sows.data.length} SOW{sows.data.length === 1 ? '' : 's'}</Badge>}
        </div>
        {sows.isLoading ? (
          <Spinner label="Loading SOWs" />
        ) : sows.data?.length ? (
          <div className="space-y-3">
            {sows.data.map((s) => (
              <div key={s.id} className="overflow-hidden rounded-2xl border border-slate-200">
                <button
                  className="flex w-full items-center justify-between gap-3 p-4 text-left hover:bg-slate-50/60"
                  onClick={() => setSelectedSow((cur) => (cur === s.id ? null : s.id))}
                >
                  <div className="flex min-w-0 items-center gap-3">
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-brand-teal to-brand-cyan text-white">
                      <FileText size={16} />
                    </span>
                    <div className="min-w-0">
                      <div className="truncate font-display font-bold text-navy-900">{s.sow_title ?? 'Untitled SOW'}</div>
                      <div className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-xs text-slate-500">
                        <span>v{s.version}</span>
                        {s.created_by && <><span className="text-slate-300">·</span><span>{s.created_by}</span></>}
                        <span className="text-slate-300">·</span>
                        <span title={new Date(s.created_at).toLocaleString()}>{formatRelative(s.created_at)}</span>
                      </div>
                    </div>
                  </div>
                  <Badge tone={s.status === 'draft' ? 'neutral' : s.status === 'sent' ? 'teal' : 'neutral'}>{s.status}</Badge>
                </button>
                {selectedSow === s.id && (
                  <div className="border-t border-slate-100 p-4">
                    <div className="mb-3 flex items-center gap-2">
                      <Button variant="outline" className="!px-3 !py-1.5 text-xs" icon={<Download size={13} />} onClick={() => downloadSow(s.id, `${s.sow_title ?? 'SOW'}.docx`)}>
                        Download
                      </Button>
                      <Button variant="outline" className="!px-3 !py-1.5 text-xs" icon={<Mail size={13} />} disabled={sendEmailMutation.isPending} onClick={() => sendEmailMutation.mutate(s.id)}>
                        {sendEmailMutation.isPending ? 'Sending…' : 'Email to customer'}
                      </Button>
                      <Button variant="ghost" className="!px-3 !py-1.5 text-xs text-red-500" icon={<Trash2 size={13} />} onClick={() => { if (confirm('Delete this SOW?')) deleteSowMutation.mutate(s.id) }}>
                        Delete
                      </Button>
                    </div>
                    <iframe title={s.sow_title ?? 'SOW'} srcDoc={s.content_html ?? ''} className="h-80 w-full rounded-xl border border-slate-200 bg-white" />
                  </div>
                )}
              </div>
            ))}
          </div>
        ) : (
          <EmptyState message="No SOWs generated for this opportunity yet" />
        )}
      </Panel>

      {preview && (
        <FilePreviewModal
          filename={preview.filename}
          content={preview.content}
          blobUrl={preview.blobUrl}
          loading={preview.loading}
          error={preview.error}
          onClose={() => {
            if (preview.blobUrl) URL.revokeObjectURL(preview.blobUrl)
            setPreview(null)
          }}
        />
      )}
    </div>
  )
}

function FinancialsTab({ customerId }: { customerId: number }) {
  const queryClient = useQueryClient()
  const { data: fin } = useQuery({
    queryKey: ['financials', customerId],
    queryFn: () => customerApi.financials(customerId),
  })
  const [form, setForm] = useState({
    expected_mrr: '',
    expected_arr: '',
    credits_requested: '',
    credits_gets: '',
    phases_to_distribute: '',
  })

  useEffect(() => {
    if (fin) {
      setForm({
        expected_mrr: fin.expected_mrr != null ? String(fin.expected_mrr) : '',
        expected_arr: fin.expected_arr != null ? String(fin.expected_arr) : '',
        credits_requested: fin.credits_requested != null ? String(fin.credits_requested) : '',
        credits_gets: fin.credits_gets != null ? String(fin.credits_gets) : '',
        phases_to_distribute: fin.phases_to_distribute != null ? String(fin.phases_to_distribute) : '',
      })
    }
  }, [fin])

  const saveMutation = useMutation({
    mutationFn: () =>
      customerApi.updateFinancials(customerId, {
        expected_mrr: form.expected_mrr === '' ? null : Number(form.expected_mrr),
        expected_arr: form.expected_arr === '' ? null : Number(form.expected_arr),
        credits_requested: form.credits_requested === '' ? null : Number(form.credits_requested),
        credits_gets: form.credits_gets === '' ? null : Number(form.credits_gets),
        phases_to_distribute: form.phases_to_distribute === '' ? null : Number(form.phases_to_distribute),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['financials', customerId] })
      queryClient.invalidateQueries({ queryKey: ['dashboard'] })
    },
  })

  const cards = [
    { label: 'Expected MRR', value: fin?.expected_mrr, bg: 'from-brand-cyan to-brand-teal', sign: true },
    { label: 'Expected ARR', value: fin?.expected_arr, bg: 'from-brand-teal to-brand-teal-dark', sign: true },
    { label: 'Credits requested', value: fin?.credits_requested, bg: 'from-amber-400 to-orange-500', sign: true },
    { label: 'Credits gets', value: fin?.credits_gets, bg: 'from-violet-500 to-purple-600', sign: true },
    { label: 'Phases to distribute', value: fin?.phases_to_distribute, bg: 'from-sky-500 to-cyan-600', sign: false },
  ]

  function field(key: keyof typeof form, fallback: string) {
    return {
      placeholder: fallback,
      value: form[key],
      onChange: (e: React.ChangeEvent<HTMLInputElement>) =>
        setForm((f) => ({ ...f, [key]: e.target.value })),
    }
  }

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
      <Panel className="scroll-fade">
        <PanelTitle><Banknote size={15} className="text-brand-teal" /> Financial snapshot</PanelTitle>
        <div className="stagger grid grid-cols-1 gap-4 sm:grid-cols-2">
          {cards.map((c) => (
            <div key={c.label} className="relative overflow-hidden rounded-2xl border border-slate-200 p-4 transition-all duration-300 hover:-translate-y-0.5 hover:shadow-lg">
              <div className={`absolute -right-5 -top-5 h-20 w-20 rounded-full bg-gradient-to-br ${c.bg} opacity-10`} />
              <div className="font-display text-[11px] font-bold tracking-widest text-slate-500 uppercase">{c.label}</div>
              <div className={`mt-1 font-display text-2xl font-bold ${c.sign ? 'text-navy-900' : 'text-navy-900'}`}>
                {c.value != null ? `$${Number(c.value).toLocaleString()}` : '—'}
              </div>
            </div>
          ))}
        </div>
      </Panel>

      <Panel className="scroll-fade" style={{ animationDelay: '0.1s' }}>
        <PanelTitle><Banknote size={15} className="text-brand-teal" /> Update figures</PanelTitle>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Expected MRR ($)">
            <input type="number" step="0.01" className={inputCls} {...field('expected_mrr', fin?.expected_mrr != null ? String(fin.expected_mrr) : '')} />
          </Field>
          <Field label="Expected ARR ($)">
            <input type="number" step="0.01" className={inputCls} {...field('expected_arr', fin?.expected_arr != null ? String(fin.expected_arr) : '')} />
          </Field>
          <Field label="Credits requested ($)">
            <input type="number" step="0.01" className={inputCls} {...field('credits_requested', fin?.credits_requested != null ? String(fin.credits_requested) : '')} />
          </Field>
          <Field label="Credits gets ($)">
            <input type="number" step="0.01" className={inputCls} {...field('credits_gets', fin?.credits_gets != null ? String(fin.credits_gets) : '')} />
          </Field>
          <Field label="Phases to distribute">
            <input type="number" min="1" step="1" className={inputCls} {...field('phases_to_distribute', fin?.phases_to_distribute != null ? String(fin.phases_to_distribute) : '')} />
          </Field>
        </div>
        <div className="mt-5">
          <Button onClick={() => saveMutation.mutate()} disabled={saveMutation.isPending}>
            {saveMutation.isPending ? 'Saving…' : 'Save financials'}
          </Button>
        </div>
      </Panel>
    </div>
  )
}