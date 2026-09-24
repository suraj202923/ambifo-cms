import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FileText, Mail, Plus, Send, Trash2, Copy, Settings, UserMinus, RefreshCcw, Eye, X, Lock, ChevronLeft, ChevronRight, Search, AlertCircle, Clock, FileSpreadsheet, Check, AlertTriangle } from 'lucide-react'
import { customerApi, emailApi } from '../api'
import type { BulkEmailMode, EmailBulkResult, EmailLog } from '../api/types'
import { Badge, Button, EmptyState, Field, inputCls, PageHead, Panel, selectCls, Spinner } from '../components/ui'
import { EmailMacroPalette } from '../components/EmailMacroPalette'

export default function EmailPage() {
  const [tab, setTab] = useState<'templates' | 'compose' | 'bulk' | 'logs' | 'settings' | 'unsubscribed'>('logs')

  const TABS = [
    { key: 'templates', label: 'Templates' },
    { key: 'compose', label: 'Compose' },
    { key: 'bulk', label: 'Bulk send' },
    { key: 'logs', label: 'Bulk CSV & logs' },
    { key: 'settings', label: 'Settings' },
    { key: 'unsubscribed', label: 'Unsubscribed' },
  ] as const

  return (
    <div>
      <PageHead title="Email" subtitle="Engine-rendered templates, composer, bulk sends and delivery log" />

      <div className="scroll-fade mb-5 flex gap-1 rounded-2xl border border-slate-200 bg-white p-1 shadow-sm w-fit flex-wrap">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`flex items-center gap-2 rounded-xl px-4 py-2 font-display text-sm font-bold transition-all duration-300 ${
              tab === t.key ? 'bg-navy-900 text-white shadow-md' : 'text-slate-500 hover:bg-slate-100'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div key={tab} className="animate-fade-in">
        {tab === 'templates' && <TemplatesTab />}
        {tab === 'compose' && <ComposeTab />}
        {tab === 'bulk' && <BulkEmailTab />}
        {tab === 'logs' && <LogsTab />}
        {tab === 'settings' && <SettingsTab />}
        {tab === 'unsubscribed' && <UnsubscribedTab />}
      </div>
    </div>
  )
}

function TemplatesTab() {
  const queryClient = useQueryClient()
  const templates = useQuery({ queryKey: ['email-templates'], queryFn: emailApi.templates })

  const [newName, setNewName] = useState('')
  const [newSubject, setNewSubject] = useState('')
  const [newBody, setNewBody] = useState('')

  const [preview, setPreview] = useState<{ id: number; name: string; subject: string; body: string } | null>(null)
  const [rawHtml, setRawHtml] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [confirmRemoveAll, setConfirmRemoveAll] = useState(false)

  const subjectRef = useRef<HTMLInputElement>(null)
  const bodyRef = useRef<HTMLTextAreaElement>(null)
  const [activeField, setActiveField] = useState<'subject' | 'body'>('body')

  function insertMacro(macro: string) {
    const target = activeField
    const field = target === 'subject' ? subjectRef.current : bodyRef.current
    if (!field) return
    const start = field.selectionStart ?? field.value.length
    const end = field.selectionEnd ?? field.value.length
    const next = field.value.slice(0, start) + macro + field.value.slice(end)
    if (target === 'subject') setNewSubject(next)
    else setNewBody(next)
    requestAnimationFrame(() => {
      const pos = start + macro.length
      field.focus()
      field.setSelectionRange(pos, pos)
    })
    setActiveField(target)
  }

  const createTemplate = useMutation({
    mutationFn: () =>
      emailApi.createTemplate({
        name: newName,
        subject_template: newSubject,
        body_template: newBody,
        is_active: true,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['email-templates'] })
      setNewName(''); setNewSubject(''); setNewBody('')
    },
  })

  const deleteTemplate = useMutation({
    mutationFn: (id: number) => emailApi.deleteTemplate(id),
    onSuccess: (_data, id) => {
      queryClient.invalidateQueries({ queryKey: ['email-templates'] })
      if (preview && preview.id === id) setPreview(null)
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : 'Failed to delete template'
      setDeleteError(msg)
    },
  })

  const removeAll = useMutation({
    mutationFn: () => emailApi.removeAllTemplates(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['email-templates'] })
      setPreview(null)
      setConfirmRemoveAll(false)
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : 'Failed to remove templates'
      setDeleteError(msg)
      setConfirmRemoveAll(false)
    },
  })

  const renderMutation = useMutation({
    mutationFn: ({ id, name }: { id: number; name: string }) =>
      emailApi
        .render({ recipient_email: 'preview@example.com', template_id: id })
        .then((r) => ({ id, name, ...r })),
    onSuccess: (data) => {
      setPreview(data)
      setRawHtml(false)
    },
  })

  function openPreview(id: number, name: string) {
    renderMutation.mutate({ id, name })
  }

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
      <Panel className="scroll-fade lg:col-span-2">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="flex items-center gap-2 font-display text-sm font-bold tracking-wide text-navy-900 uppercase">
            <FileText size={15} className="text-brand-teal" /> Templates
            {templates.data && <span className="text-xs font-medium text-slate-400 normal-case">({templates.data.length})</span>}
          </h2>
          {templates.data && templates.data.length > 0 && (
            <Button
              variant="outline"
              className="!px-3 !py-1.5 !text-xs"
              icon={<Trash2 size={14} />}
              disabled={removeAll.isPending}
              onClick={() => setConfirmRemoveAll(true)}
            >
              {removeAll.isPending ? 'Removing…' : 'Remove all'}
            </Button>
          )}
        </div>
        {deleteError && (
          <div className="mb-4 flex items-center justify-between gap-2 rounded-xl border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-600">
            <span>{deleteError}</span>
            <button className="shrink-0 rounded p-0.5 text-red-400 hover:bg-red-100 hover:text-red-600" onClick={() => setDeleteError(null)} title="Dismiss">
              <X size={15} />
            </button>
          </div>
        )}
        {templates.isLoading ? (
          <Spinner label="Loading templates" />
        ) : (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            {templates.data?.map((t) => (
              <div key={t.id} className="brand-card rounded-2xl border border-slate-200 bg-slate-50/50 p-5">
                <div className="mb-2 flex items-center justify-between">
                  <span className="flex items-center gap-2 font-display text-sm font-bold text-navy-900">
                    <FileText size={15} className="text-brand-teal" /> {t.name}
                  </span>
                  <div className="flex items-center gap-1">
                    <button
                      className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-brand-teal/10 hover:text-brand-teal-dark"
                      title="View template"
                      onClick={() => openPreview(t.id, t.name)}
                    >
                      <Eye size={14} />
                    </button>
                    <button
                      className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-200 hover:text-slate-700"
                      title="Copy subject"
                      onClick={() => navigator.clipboard.writeText(t.subject_template)}
                    >
                      <Copy size={14} />
                    </button>
                    {t.is_system ? (
                      <span
                        className="rounded-lg p-1.5 text-slate-300"
                        title="System template — cannot be deleted"
                      >
                        <Lock size={14} />
                      </span>
                    ) : (
                      <button
                        className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-red-50 hover:text-red-600"
                        title="Delete"
                        onClick={() => { setDeleteError(null); deleteTemplate.mutate(t.id) }}
                      >
                        <Trash2 size={14} />
                      </button>
                    )}
                  </div>
                </div>
                <p className="truncate text-sm text-slate-600">{t.subject_template}</p>
                <p className="mt-1 whitespace-pre-wrap text-xs text-slate-500">
                  {t.body_template.replace(/<[^>]*>/g, '').slice(0, 120)}
                  {t.body_template.replace(/<[^>]*>/g, '').length > 120 ? '…' : ''}
                </p>
                {t.is_system && (
                  <div className="mt-2">
                    <Badge tone="neutral">system</Badge>
                  </div>
                )}
              </div>
            ))}
            {templates.data?.length === 0 && <EmptyState message="No templates yet" />}
          </div>
        )}
      </Panel>

      <Panel className="scroll-fade h-fit" style={{ animationDelay: '0.1s' }}>
        <h2 className="mb-4 flex items-center gap-2 font-display text-sm font-bold tracking-wide text-navy-900 uppercase">
          <Plus size={15} className="text-brand-teal" /> New template
        </h2>
        <form
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault()
            if (newName.trim() && newSubject.trim() && newBody.trim()) createTemplate.mutate()
          }}
        >
          <Field label="Name">
            <input className={inputCls} value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="demo_followup" required />
          </Field>
          <Field label="Subject ({{macro}} supported)">
            <input ref={subjectRef} className={inputCls} value={newSubject} onChange={(e) => setNewSubject(e.target.value)} onFocus={() => setActiveField('subject')} placeholder="Thanks {{customer_name}}" required />
          </Field>
          <Field label="Body Template (HTML supported, {{macro}} supported)">
            <textarea
              ref={bodyRef}
              className={`${inputCls} min-h-[160px] font-mono text-xs`}
              value={newBody}
              onChange={(e) => setNewBody(e.target.value)}
              onFocus={() => setActiveField('body')}
              placeholder={'<p>Hi {{customer_name}},</p>\n<p>Thanks for your interest in <strong>{{cloud}}</strong>.</p>'}
              required
            />
          </Field>
          <EmailMacroPalette onInsert={insertMacro} />
          <Button disabled={createTemplate.isPending} type="submit">
            {createTemplate.isPending ? 'Saving…' : 'Create template'}
          </Button>
        </form>
      </Panel>

      {preview && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-navy-900/60 p-4 backdrop-blur-sm"
          role="dialog"
          aria-modal="true"
          onClick={() => setPreview(null)}
        >
          <div
            className="scroll-fade max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-4 flex items-center justify-between">
              <h3 className="flex items-center gap-2 font-display text-base font-bold text-navy-900">
                <Eye size={16} className="text-brand-teal" /> {preview.name}
              </h3>
              <div className="flex items-center gap-2">
                <button
                  className="rounded-lg px-2.5 py-1.5 font-display text-xs font-bold text-slate-500 hover:bg-slate-100"
                  onClick={() => setRawHtml((v) => !v)}
                >
                  {rawHtml ? 'Rendered view' : 'Source HTML'}
                </button>
                <button className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700" title="Close" onClick={() => setPreview(null)}>
                  <X size={18} />
                </button>
              </div>
            </div>

            <div className="mb-4 rounded-xl border border-slate-200 bg-slate-50 p-4">
              <div className="mb-1 font-display text-[11px] font-bold tracking-widest text-slate-500 uppercase">Subject</div>
              <p className="font-display font-semibold text-navy-900">{preview.subject}</p>
            </div>

            <div className="overflow-hidden rounded-xl border border-slate-200">
              <div className="border-b border-slate-200 bg-slate-50 px-4 py-2 font-display text-[11px] font-bold tracking-widest text-slate-500 uppercase">
                Body
              </div>
              {renderMutation.isPending ? (
                <div className="p-6"><Spinner label="Rendering HTML" /></div>
              ) : rawHtml ? (
                <pre className="bg-slate-950 p-4 text-xs leading-relaxed text-slate-100 whitespace-pre-wrap">{preview.body}</pre>
              ) : (
                <div
                  className="email-body p-6"
                  dangerouslySetInnerHTML={{ __html: preview.body }}
                />
              )}
            </div>
          </div>
        </div>
      )}

      {confirmRemoveAll && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-navy-900/60 p-4 backdrop-blur-sm"
          role="alertdialog"
          aria-modal="true"
          onClick={() => setConfirmRemoveAll(false)}
        >
          <div
            className="scroll-fade w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-2 flex items-center gap-2">
              <Trash2 size={18} className="text-red-500" />
              <h3 className="font-display text-base font-bold text-navy-900">Remove all templates?</h3>
            </div>
            <p className="mb-5 text-sm text-slate-600">
              This deletes every email template. System templates will be re-created automatically on the next page
              load the app needs them (they are required for meeting and SOW emails). This cannot be undone.
            </p>
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setConfirmRemoveAll(false)}>Cancel</Button>
              <Button
                className="!bg-red-500 hover:!bg-red-600"
                icon={<Trash2 size={15} />}
                disabled={removeAll.isPending}
                onClick={() => removeAll.mutate()}
              >
                {removeAll.isPending ? 'Removing…' : 'Remove all'}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function ComposeTab() {
  const queryClient = useQueryClient()
  const templates = useQuery({ queryKey: ['email-templates'], queryFn: emailApi.templates })

  const [form, setForm] = useState({
    recipient_email: '',
    template_id: '',
    subject: '',
    body: '',
    varNames: '',
    cc_emails: '',
    bcc_emails: '',
  })
  const [preview, setPreview] = useState<{ subject: string; body: string } | null>(null)

  function contextFromVars(): Record<string, string> {
    const ctx: Record<string, string> = {}
    for (const pair of form.varNames.split(',')) {
      const [k, ...rest] = pair.trim().split('=')
      if (k) ctx[k.trim()] = rest.join('=').trim()
    }
    return ctx
  }

  const renderMutation = useMutation({
    mutationFn: () =>
      emailApi.render({
        recipient_email: form.recipient_email || 'preview@example.com',
        template_id: form.template_id ? Number(form.template_id) : null,
        subject: form.subject || undefined,
        body: form.body || undefined,
        context: contextFromVars(),
      }),
    onSuccess: (data) => setPreview(data),
  })

  const sendMutation = useMutation({
    mutationFn: () =>
      emailApi.send({
        email_type: 'general',
        recipient_email: form.recipient_email,
        template_id: form.template_id ? Number(form.template_id) : null,
        subject: form.subject || undefined,
        body: form.body || undefined,
        context: contextFromVars(),
        cc_emails: form.cc_emails ? form.cc_emails.split(',').map(e => e.trim()).filter(Boolean) : undefined,
      }),
    onSuccess: () => {
      setPreview(null)
      setForm({ recipient_email: '', template_id: '', subject: '', body: '', varNames: '', cc_emails: '', bcc_emails: '' })
      queryClient.invalidateQueries({ queryKey: ['email-logs'] })
    },
  })

  const templateId = form.template_id ? Number(form.template_id) : null

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
      <Panel className="scroll-fade">
        <h2 className="mb-4 flex items-center gap-2 font-display text-sm font-bold tracking-wide text-navy-900 uppercase">
          <Send size={15} className="text-brand-teal" /> Compose
        </h2>
        <form
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault()
            sendMutation.mutate()
          }}
        >
          <Field label="Template (optional)">
            <select
              className={selectCls}
              value={form.template_id}
              onChange={(e) => setForm((f) => ({ ...f, template_id: e.target.value }))}
            >
              <option value="">— blank template —</option>
              {templates.data?.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name} · {t.subject_template}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Recipient *">
            <input className={inputCls} type="email" required value={form.recipient_email} onChange={(e) => setForm((f) => ({ ...f, recipient_email: e.target.value }))} placeholder="client@company.com" />
          </Field>
          <Field label="CC emails (comma separated)">
            <input className={inputCls} value={form.cc_emails} onChange={(e) => setForm((f) => ({ ...f, cc_emails: e.target.value }))} placeholder="cc1@x.com, cc2@y.com" />
          </Field>
          <Field label="Variables (comma-separated name=value)">
            <input className={inputCls} value={form.varNames} onChange={(e) => setForm((f) => ({ ...f, varNames: e.target.value }))} placeholder="customer_name=Acme Corp, cloud=AWS" />
          </Field>
          <Field label="Subject override">
            <input className={inputCls} value={form.subject} onChange={(e) => setForm((f) => ({ ...f, subject: e.target.value }))} placeholder={templateId ? undefined : 'Hello {{customer_name}}'} />
          </Field>
          <Field label="Body override">
            <textarea className={`${inputCls} min-h-[120px]`} value={form.body} onChange={(e) => setForm((f) => ({ ...f, body: e.target.value }))} placeholder={templateId ? undefined : 'Hi {{customer_name}},…'} />
          </Field>
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" icon={<Mail size={15} />} onClick={(e) => { e.preventDefault(); renderMutation.mutate() }} disabled={renderMutation.isPending}>
              {renderMutation.isPending ? 'Rendering…' : 'Preview'}
            </Button>
            <Button type="submit" icon={<Send size={15} />} disabled={sendMutation.isPending || !form.recipient_email}>
              {sendMutation.isPending ? 'Sending…' : 'Send via engine'}
            </Button>
          </div>
        </form>
      </Panel>

      <Panel className="scroll-fade" style={{ animationDelay: '0.1s' }}>
        <h2 className="mb-4 flex items-center gap-2 font-display text-sm font-bold tracking-wide text-navy-900 uppercase">
          <Mail size={15} className="text-brand-teal" /> Preview
        </h2>
        {preview ? (
          <div className="space-y-3">
            <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
              <div className="mb-1 font-display text-[11px] font-bold tracking-widest text-slate-500 uppercase">Subject</div>
              <p className="font-display font-semibold text-navy-900">{preview.subject}</p>
            </div>
            <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
              <div className="mb-1 font-display text-[11px] font-bold tracking-widest text-slate-500 uppercase">Body</div>
              <p className="whitespace-pre-wrap text-sm text-slate-700">{preview.body}</p>
            </div>
          </div>
        ) : (
          <EmptyState message="Rendered output will appear here" />
        )}
      </Panel>
    </div>
  )
}

function BulkEmailTab() {
  const queryClient = useQueryClient()
  const lookups = useQuery({ queryKey: ['lookups'], queryFn: () => customerApi.lookups() })
  const customers = useQuery({ queryKey: ['customers'], queryFn: () => customerApi.list({ limit: 500 }) })
  const templates = useQuery({ queryKey: ['email-templates'], queryFn: () => emailApi.templates() })
  const logs = useQuery({ queryKey: ['email-logs'], queryFn: () => emailApi.logs() })

  const [mode, setMode] = useState<BulkEmailMode>('all_customers')
  const [templateId, setTemplateId] = useState('')
  const [subject, setSubject] = useState('')
  const [body, setBody] = useState('')
  const [filterValue, setFilterValue] = useState('')
  const [selectedIds, setSelectedIds] = useState<number[]>([])
  const [manual, setManual] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<EmailBulkResult | null>(null)

  const sendMutation = useMutation({
    mutationFn: () =>
      emailApi.bulk({
        mode,
        template_id: templateId ? Number(templateId) : null,
        subject: subject || null,
        body: body || null,
        filter_value: filterValue || null,
        customer_ids: mode === 'select_customers' ? selectedIds : undefined,
        manual_emails: manual.split(/[\n,\s]+/).map((m) => m.trim()).filter(Boolean),
      }),
    onSuccess: (res) => {
      setResult(res)
      queryClient.invalidateQueries({ queryKey: ['email-logs'] })
    },
    onError: (e) => setError(e instanceof Error ? e.message : 'Bulk send failed'),
  })

  const retryMutation = useMutation({
    mutationFn: () => emailApi.retryFailed(),
    onSuccess: (res) => {
      setResult(res)
      queryClient.invalidateQueries({ queryKey: ['email-logs'] })
    },
    onError: (e) => setError(e instanceof Error ? e.message : 'Retry failed'),
  })

  const recipientCount = mode === 'all_customers'
    ? (customers.data?.filter((c) => c.email).length ?? 0)
    : mode === 'customers_by_status' || mode === 'customers_by_segment'
      ? (customers.data?.filter((c) => (mode === 'customers_by_status' ? c.deal_status === filterValue : c.segment === filterValue) && c.email).length ?? 0)
      : mode === 'select_customers'
        ? selectedIds.length
        : mode === 'manual_emails'
          ? manual.split(/[\n,\s]+/).filter(Boolean).length
          : '? (leads)'

  const failedCount = logs.data?.items?.filter((l) => l.status === 'failed').length ?? 0

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
      <Panel className="scroll-fade lg:col-span-2">
        <h2 className="mb-4 flex items-center gap-2 font-display text-sm font-bold tracking-wide text-navy-900 uppercase">
          <Mail size={15} className="text-brand-teal" /> Send bulk email
        </h2>
        <form
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault()
            setError(null)
            setResult(null)
            sendMutation.mutate()
          }}
        >
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label="Recipients">
              <select className={selectCls} value={mode} onChange={(e) => setMode(e.target.value as BulkEmailMode)}>
                <option value="all_customers">All customers</option>
                <option value="all_leads">All active leads</option>
                <option value="customers_by_status">Customers by deal status</option>
                <option value="customers_by_segment">Customers by segment</option>
                <option value="select_customers">Select specific customers</option>
                <option value="manual_emails">Manual email list</option>
              </select>
            </Field>
            <Field label="Template (optional)">
              <select className={selectCls} value={templateId} onChange={(e) => setTemplateId(e.target.value)}>
                <option value="">— raw subject/body —</option>
                {templates.data?.map((t) => (
                  <option key={t.id} value={t.id}>{t.name}</option>
                ))}
              </select>
            </Field>
            {(mode === 'customers_by_status' || mode === 'customers_by_segment') && (
              <Field label={mode === 'customers_by_status' ? 'Deal status' : 'Segment'}>
                <select className={selectCls} value={filterValue} onChange={(e) => setFilterValue(e.target.value)}>
                  <option value="">— select —</option>
                  {(mode === 'customers_by_status' ? lookups.data?.statuses : lookups.data?.segments)?.map((s) => (
                    <option key={s.id} value={s.name}>{s.name}</option>
                  ))}
                </select>
              </Field>
            )}
            {mode === 'manual_emails' && (
              <Field label="Emails (comma or line separated)">
                <textarea className={`${inputCls} min-h-[70px] font-mono text-xs`} value={manual} onChange={(e) => setManual(e.target.value)} placeholder="a@x.com, b@y.com" />
              </Field>
            )}
            {mode === 'select_customers' && (
              <Field label="Select customers">
                <div className="max-h-[200px] space-y-1 overflow-y-auto rounded-xl border border-slate-200 p-2">
                  {customers.data?.filter(c => c.email).map((c) => (
                    <label key={c.id} className="flex items-center gap-2 text-xs text-slate-600 hover:bg-slate-50 rounded-lg px-2 py-1">
                      <input type="checkbox" className="h-3.5 w-3.5 accent-brand-teal" checked={selectedIds.includes(c.id)} onChange={(e) => {
                        setSelectedIds((ids) => e.target.checked ? [...ids, c.id] : ids.filter((id) => id !== c.id))
                      }} />
                      <span className="truncate">{c.customer_name}</span>
                      <span className="ml-auto text-slate-400">{c.email}</span>
                    </label>
                  ))}
                </div>
              </Field>
            )}
            <Field label="Subject">
              <input className={inputCls} value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="Supports {{customer_name}}" />
            </Field>
            <Field label="Body">
              <textarea className={`${inputCls} min-h-[140px]`} value={body} onChange={(e) => setBody(e.target.value)} placeholder="Hi {{customer_name}},…" />
            </Field>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <Button icon={<Mail size={15} />} disabled={sendMutation.isPending}>
              {sendMutation.isPending ? 'Sending…' : 'Send to all'}
            </Button>
            <Button variant="ghost" disabled>
              <RefreshCcw size={14} /> will target {recipientCount} recipient(s)
            </Button>
          </div>
        </form>

        <div className="mt-6 rounded-2xl border border-slate-200 p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2 font-display text-sm font-bold text-navy-900">
              <RefreshCcw size={15} className="text-brand-teal" /> Failed emails
              <Badge tone={failedCount > 0 ? 'coral' : 'green'}>{failedCount}</Badge>
            </div>
            <Button variant="secondary" className="!px-3 !py-1.5 text-xs" disabled={retryMutation.isPending || failedCount === 0} onClick={() => { setError(null); setResult(null); retryMutation.mutate() }}>
              {retryMutation.isPending ? 'Re-queuing…' : 'Retry all failed'}
            </Button>
          </div>
        </div>
      </Panel>

      <Panel className="scroll-fade h-fit lg:col-span-1" style={{ animationDelay: '0.1s' }}>
        <h2 className="mb-4 flex items-center gap-2 font-display text-sm font-bold tracking-wide text-navy-900 uppercase">
          <Mail size={15} className="text-brand-teal" /> Result
        </h2>
        {sendMutation.isPending || retryMutation.isPending ? (
          <Spinner label="Working…" />
        ) : result ? (
          <div className={result.failed > 0 ? 'rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-700' : 'rounded-xl border border-green-200 bg-green-50 p-4 text-sm text-green-700'}>
            <div className="font-display font-bold">
              {result.queued} queued · {result.failed} failed · {result.attempted} attempted
            </div>
            <div className="mt-1 text-xs">mode: {result.mode}</div>
            {result.errors.length > 0 && (
              <ul className="mt-2 max-h-40 list-inside list-disc space-y-0.5 overflow-y-auto text-xs">
                {result.errors.map((e, i) => <li key={i}>{e}</li>)}
              </ul>
            )}
          </div>
        ) : (
          <EmptyState message="Run a bulk send to see the outcome" />
        )}
        {error && <div className="mt-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-600">⚠ {error}</div>}
      </Panel>
    </div>
  )
}

function useDebounced<T>(value: T, delay = 350): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(t)
  }, [value, delay])
  return debounced
}

function formatRelative(iso: string) {
  const then = new Date(iso).getTime()
  const diff = Date.now() - then
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.floor(hrs / 24)
  if (days < 30) return `${days}d ago`
  return new Date(iso).toLocaleDateString()
}

function logStatusTone(status: string) {
  if (status === 'sent') return 'green'
  if (status === 'failed') return 'coral'
  if (status === 'queued') return 'cyan'
  if (status === 'processing') return 'navy'
  return 'neutral'
}

const LOG_PAGE_SIZE = 25

function LogsTab() {
  const queryClient = useQueryClient()
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('')
  const [page, setPage] = useState(1)
  const [viewing, setViewing] = useState<EmailLog | null>(null)
  const debouncedSearch = useDebounced(search)

  const stats = useQuery({
    queryKey: ['email-log-stats'],
    queryFn: emailApi.stats,
    refetchInterval: (query) => {
      const s = query.state.data as { queued?: number; processing?: number } | undefined
      return (s?.queued ?? 0) > 0 || (s?.processing ?? 0) > 0 ? 1200 : false
    },
  })

  const statsActive = (stats.data?.queued ?? 0) > 0 || (stats.data?.processing ?? 0) > 0

  const logs = useQuery({
    queryKey: ['email-logs', { q: debouncedSearch, status, page }],
    queryFn: () =>
      emailApi.logs({
        q: debouncedSearch || undefined,
        status: status || undefined,
        page,
        page_size: LOG_PAGE_SIZE,
      }),
    refetchInterval: statsActive ? 1200 : false,
  })

  const kpis = useMemo(() => {
    const s = stats.data
    if (!s) return { total: 0, sent: 0, failed: 0, queued: 0, processing: 0, devMode: 0 }
    return { total: s.total, sent: s.sent, failed: s.failed, queued: s.queued, processing: s.processing, devMode: s.dev_mode }
  }, [stats.data])

  const retryMutation = useMutation({
    mutationFn: (logId: number) => emailApi.retryLog(logId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['email-logs'] })
      queryClient.invalidateQueries({ queryKey: ['email-log-stats'] })
    },
  })

  const resendMutation = useMutation({
    mutationFn: (logId: number) => emailApi.resendLog(logId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['email-logs'] })
      queryClient.invalidateQueries({ queryKey: ['email-log-stats'] })
    },
  })

  const totalPages = Math.max(1, Math.ceil((logs.data?.total ?? 0) / LOG_PAGE_SIZE))
  const items = logs.data?.items ?? []

  const statusTabs = [
    { key: '', label: 'All' },
    { key: 'sent', label: 'Sent' },
    { key: 'failed', label: 'Failed' },
    { key: 'queued', label: 'Queued' },
    { key: 'processing', label: 'Processing' },
    { key: 'dev-mode', label: 'Dev mode' },
  ]

  const kpiStrip = [
    { label: 'Total sends', value: kpis.total, sub: `${kpis.sent} sent · ${kpis.devMode} dev · ${kpis.failed} failed`, icon: Send, bg: 'from-brand-teal to-brand-teal-dark' },
    { label: 'Sent', value: kpis.sent, sub: kpis.sent > 0 ? `${Math.round((kpis.total ? kpis.sent / kpis.total : 0) * 100)}% of total` : 'no SMTP sent yet', icon: Mail, bg: 'from-green-500 to-emerald-600' },
    { label: 'Failed', value: kpis.failed, sub: 'need attention', icon: AlertCircle, bg: 'from-red-500 to-rose-600' },
    { label: 'Queued', value: kpis.queued + kpis.processing, sub: `${kpis.queued} queued · ${kpis.processing} processing`, icon: Clock, bg: 'from-navy-700 to-navy-900' },
    { label: 'Dev mode', value: kpis.devMode, sub: kpis.devMode > 0 ? `${kpis.devMode} emails logged` : 'no SMTP · logged only', icon: FileText, bg: 'from-amber-400 to-orange-500' },
  ]

  return (
    <div className="space-y-5">
      <CsvBulkTab />

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        {kpiStrip.map((k) => {
          const Icon = k.icon
          return (
            <div key={k.label} className={`rounded-2xl bg-gradient-to-br ${k.bg} p-4 text-white shadow-lg`}>
              <div className="flex items-center justify-between">
                <span className="font-display text-[11px] font-bold tracking-widest text-white/70 uppercase">{k.label}</span>
                <Icon size={16} className="text-white/50" />
              </div>
              <div className="mt-1 font-display text-3xl font-extrabold">{k.value.toLocaleString()}</div>
              <div className="mt-1 text-xs text-white/70">{k.sub}</div>
            </div>
          )
        })}
      </div>

      <Panel className="scroll-fade">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap gap-1 rounded-2xl border border-slate-200 bg-white p-1">
            {statusTabs.map((t) => (
              <button
                key={t.key}
                onClick={() => { setStatus(t.key); setPage(1) }}
                className={`rounded-xl px-3.5 py-1.5 font-display text-xs font-bold transition-all ${status === t.key ? 'bg-navy-900 text-white shadow-sm' : 'text-slate-500 hover:bg-slate-100'}`}
              >
                {t.label}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-2">
            <div className="relative">
              <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                className={`${inputCls} w-60 pl-9`}
                value={search}
                onChange={(e) => { setSearch(e.target.value); setPage(1) }}
                placeholder="Search recipient or subject…"
              />
            </div>
            <Button variant="outline" icon={<RefreshCcw size={15} />} disabled={logs.isFetching} onClick={() => { queryClient.invalidateQueries({ queryKey: ['email-logs'] }); queryClient.invalidateQueries({ queryKey: ['email-log-stats'] }) }}>
              Refresh
            </Button>
          </div>
        </div>

        {logs.isLoading ? (
          <Spinner label="Loading sent logs" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-slate-100 bg-slate-50/80 font-display text-[11px] font-bold tracking-widest text-slate-500 uppercase">
                  <th className="px-4 py-3">Recipient</th>
                  <th className="px-4 py-3">Subject</th>
                  <th className="px-4 py-3">Type</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3">Queue</th>
                  <th className="px-4 py-3">Sent</th>
                  <th className="px-4 py-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {items.map((l) => (
                  <tr key={l.id} className="border-b border-slate-50 last:border-0 hover:bg-brand-teal/[0.04]">
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2.5">
                        <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-gradient-to-br from-brand-teal to-brand-teal-dark text-xs font-bold text-white">
                          {(l.recipient_email ?? '?').charAt(0).toUpperCase()}
                        </span>
                        <div className="min-w-0">
                          <div className="truncate font-semibold text-navy-900 max-w-[180px]">{l.recipient_email ?? '—'}</div>
                          {l.retry_count > 0 && <div className="text-[11px] text-red-500">{l.retry_count} retr{l.retry_count === 1 ? 'y' : 'ies'}</div>}
                        </div>
                      </div>
                    </td>
                    <td className="max-w-[220px] truncate px-4 py-3 text-slate-600">{l.subject}</td>
                    <td className="px-4 py-3"><Badge tone="neutral">{l.email_type}</Badge></td>
                    <td className="px-4 py-3">
                      <span className="inline-flex items-center gap-1.5">
                        <span className={`h-2 w-2 rounded-full ${l.status === 'sent' ? 'bg-green-500' : l.status === 'failed' ? 'bg-red-500' : l.status === 'queued' ? 'bg-cyan-400' : l.status === 'processing' ? 'bg-navy-500 animate-pulse' : 'bg-slate-400'}`} />
                        <Badge tone={logStatusTone(l.status)}>{l.status}</Badge>
                      </span>
                    </td>
                    <td className="px-4 py-3"><Badge tone="neutral">{l.queue_status}</Badge></td>
                    <td className="px-4 py-3 text-xs text-slate-400" title={new Date(l.created_at).toLocaleString()}>{formatRelative(l.created_at)}</td>
                    <td className="px-4 py-3">
                      <div className="flex items-center justify-end gap-1">
                        <button className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-brand-teal/10 hover:text-brand-teal-dark" title="View email" onClick={() => setViewing(l)}>
                          <Eye size={15} />
                        </button>
                        {l.status === 'failed' && (
                          <Button variant="ghost" className="!px-2 !py-1 text-xs" disabled={retryMutation.isPending} onClick={() => retryMutation.mutate(l.id)}>
                            <RefreshCcw size={12} /> Retry
                          </Button>
                        )}
                        <Button variant="ghost" className="!px-2 !py-1 text-xs" disabled={resendMutation.isPending} onClick={() => resendMutation.mutate(l.id)}>
                          <Send size={12} /> Resend
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
                {items.length === 0 && (
                  <tr><td colSpan={7}><EmptyState message={logs.data?.total ? 'No matching emails' : 'No emails sent yet'} /></td></tr>
                )}
              </tbody>
            </table>
          </div>
        )}

        {totalPages > 1 && items.length > 0 && (
          <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-200 bg-slate-50/60 px-4 py-3">
            <span className="text-sm text-slate-500">
              Showing <span className="font-semibold text-navy-900">{(page - 1) * LOG_PAGE_SIZE + 1}–{Math.min(page * LOG_PAGE_SIZE, logs.data?.total ?? 0)}</span>{' '}
              of <span className="font-semibold text-navy-900">{(logs.data?.total ?? 0).toLocaleString()}</span>
            </span>
            <div className="flex items-center gap-1">
              <Button variant="ghost" icon={<ChevronLeft size={16} />} disabled={page <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))}>Prev</Button>
              <span className="min-w-[80px] text-center font-display text-xs font-bold tracking-widest text-slate-500 uppercase">Page {page} / {totalPages}</span>
              <Button variant="ghost" onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page >= totalPages}>Next <ChevronRight size={16} /></Button>
            </div>
          </div>
        )}
      </Panel>

      {viewing && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-navy-900/60 p-4 backdrop-blur-sm"
          role="dialog"
          aria-modal="true"
          onClick={() => setViewing(null)}
        >
          <div
            className="scroll-fade max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-4 flex items-start justify-between gap-3">
              <div className="min-w-0">
                <h3 className="flex items-center gap-2 font-display text-base font-bold text-navy-900">
                  <Mail size={16} className="text-brand-teal" /> {viewing.subject}
                </h3>
                <p className="mt-1 text-sm text-slate-500">To {viewing.recipient_email ?? '—'}</p>
              </div>
              <button className="shrink-0 rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700" title="Close" onClick={() => setViewing(null)}>
                <X size={18} />
              </button>
            </div>

            <div className="mb-4 flex flex-wrap gap-2">
              <Badge tone={logStatusTone(viewing.status)}>{viewing.status}</Badge>
              <Badge tone="neutral">{viewing.queue_status}</Badge>
              <Badge tone="neutral">{viewing.email_type}</Badge>
              <span className="text-xs text-slate-400" title={new Date(viewing.created_at).toLocaleString()}>{formatRelative(viewing.created_at)}</span>
            </div>

            {viewing.error_message && (
              <div className="mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-600">{viewing.error_message}</div>
            )}

            <div className="overflow-hidden rounded-xl border border-slate-200">
              <div className="border-b border-slate-200 bg-slate-50 px-4 py-2 font-display text-[11px] font-bold tracking-widest text-slate-500 uppercase">Body</div>
              {viewing.body.includes('<') ? (
                <div className="email-body p-6" dangerouslySetInnerHTML={{ __html: viewing.body }} />
              ) : (
                <pre className="whitespace-pre-wrap p-6 text-sm text-slate-700">{viewing.body}</pre>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function SettingsTab() {
  const queryClient = useQueryClient()
  const settings = useQuery({ queryKey: ['email-settings'], queryFn: emailApi.settings })

  const [form, setForm] = useState({
    smtp_host: '',
    smtp_port: 587,
    smtp_username: '',
    smtp_password: '',
    smtp_use_tls: true,
    smtp_mail_from: '',
    app_base_url: '',
  })
  const [testEmail, setTestEmail] = useState('')
  const [loaded, setLoaded] = useState(false)

  if (settings.data && !loaded) {
    setForm({
      smtp_host: settings.data.smtp_host,
      smtp_port: settings.data.smtp_port,
      smtp_username: settings.data.smtp_username,
      smtp_password: '',
      smtp_use_tls: settings.data.smtp_use_tls,
      smtp_mail_from: settings.data.smtp_mail_from,
      app_base_url: settings.data.app_base_url,
    })
    setLoaded(true)
  }

  const saveMutation = useMutation({
    mutationFn: () => emailApi.updateSettings({
      smtp_host: form.smtp_host || null,
      smtp_port: form.smtp_port,
      smtp_username: form.smtp_username || null,
      smtp_password: form.smtp_password || null,
      smtp_use_tls: form.smtp_use_tls,
      smtp_mail_from: form.smtp_mail_from || null,
      app_base_url: form.app_base_url || null,
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['email-settings'] })
    },
  })

  const testMutation = useMutation({
    mutationFn: () => emailApi.testSmtp(testEmail),
  })

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
      <Panel className="scroll-fade">
        <h2 className="mb-4 flex items-center gap-2 font-display text-sm font-bold tracking-wide text-navy-900 uppercase">
          <Settings size={15} className="text-brand-teal" /> SMTP Settings
        </h2>
        {settings.isLoading ? <Spinner label="Loading settings" /> : (
          <form className="flex flex-col gap-4" onSubmit={(e) => { e.preventDefault(); saveMutation.mutate() }}>
            <Field label="SMTP Host">
              <input className={inputCls} value={form.smtp_host} onChange={(e) => setForm((f) => ({ ...f, smtp_host: e.target.value }))} placeholder="smtp.gmail.com" />
            </Field>
            <div className="grid grid-cols-2 gap-4">
              <Field label="Port">
                <input className={inputCls} type="number" value={form.smtp_port} onChange={(e) => setForm((f) => ({ ...f, smtp_port: Number(e.target.value) }))} />
              </Field>
              <Field label="Use TLS">
                <select className={selectCls} value={String(form.smtp_use_tls)} onChange={(e) => setForm((f) => ({ ...f, smtp_use_tls: e.target.value === 'true' }))}>
                  <option value="true">Yes</option>
                  <option value="false">No</option>
                </select>
              </Field>
            </div>
            <Field label="Username">
              <input className={inputCls} value={form.smtp_username} onChange={(e) => setForm((f) => ({ ...f, smtp_username: e.target.value }))} />
            </Field>
            <Field label="Password">
              <input className={inputCls} type="password" value={form.smtp_password} onChange={(e) => setForm((f) => ({ ...f, smtp_password: e.target.value }))} placeholder={settings.data?.smtp_password_set ? '(set)' : ''} />
            </Field>
            <Field label="Mail From">
              <input className={inputCls} value={form.smtp_mail_from} onChange={(e) => setForm((f) => ({ ...f, smtp_mail_from: e.target.value }))} placeholder="noreply@ambifo.com" />
            </Field>
            <Field label="App Base URL">
              <input className={inputCls} value={form.app_base_url} onChange={(e) => setForm((f) => ({ ...f, app_base_url: e.target.value }))} placeholder="http://127.0.0.1:8000" />
            </Field>
            <Button type="submit" disabled={saveMutation.isPending}>{saveMutation.isPending ? 'Saving…' : 'Save settings'}</Button>
          </form>
        )}
      </Panel>

      <Panel className="scroll-fade" style={{ animationDelay: '0.1s' }}>
        <h2 className="mb-4 flex items-center gap-2 font-display text-sm font-bold tracking-wide text-navy-900 uppercase">
          <Send size={15} className="text-brand-teal" /> Test SMTP
        </h2>
        <div className="flex flex-col gap-4">
          <Field label="Send test to">
            <input className={inputCls} type="email" value={testEmail} onChange={(e) => setTestEmail(e.target.value)} placeholder="your@email.com" />
          </Field>
          <Button disabled={testMutation.isPending || !testEmail} onClick={() => testMutation.mutate()}>
            {testMutation.isPending ? 'Sending…' : 'Send test email'}
          </Button>
          {testMutation.data && (
            <div className={`rounded-xl border p-4 text-sm ${testMutation.data.ok ? 'border-green-200 bg-green-50 text-green-700' : 'border-red-200 bg-red-50 text-red-600'}`}>
              {testMutation.data.ok ? `Sent successfully (${testMutation.data.status})` : `Failed: ${testMutation.data.error}`}
            </div>
          )}
        </div>
      </Panel>
    </div>
  )
}

function CsvBulkTab() {
  const queryClient = useQueryClient()
  const templates = useQuery({ queryKey: ['email-templates'], queryFn: emailApi.templates })
  const fileRef = useRef<HTMLInputElement>(null)
  const [templateId, setTemplateId] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [result, setResult] = useState<any>(null)
  const [error, setError] = useState<string | null>(null)

  const uploadMutation = useMutation({
    mutationFn: () => emailApi.bulkCsv(file!, Number(templateId)),
    onSuccess: (res) => {
      setResult(res)
      queryClient.invalidateQueries({ queryKey: ['email-logs'] })
      queryClient.invalidateQueries({ queryKey: ['email-log-stats'] })
    },
    onError: (e) => setError(e instanceof Error ? e.message : 'Upload failed'),
  })

  function resetAll() {
    setFile(null)
    setResult(null)
    setError(null)
    if (fileRef.current) fileRef.current.value = ''
  }

  const ready = !!templateId && !!file

  return (
    <Panel className="scroll-fade">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 pb-3">
        <div className="flex items-center gap-2.5">
          <span className="grid h-7 w-7 place-items-center rounded-lg bg-gradient-to-br from-brand-teal to-brand-teal-dark text-white">
            <FileSpreadsheet size={15} />
          </span>
          <div>
            <h2 className="font-display text-sm font-bold text-navy-900">CSV Bulk Send</h2>
            <p className="text-xs text-slate-500">Upload a contact list and push every row through SMTP, one per second.</p>
          </div>
        </div>
        <Badge tone={file ? 'green' : 'neutral'}>{file ? `${file.name}` : 'No file selected'}</Badge>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_300px]">
        <div className="flex flex-col rounded-2xl border border-slate-200 bg-white p-4">
          <div className="mb-2.5 flex items-center gap-2">
            <span className="rounded-lg bg-brand-teal/10 px-2 py-0.5 font-display text-[11px] font-bold tracking-wider text-brand-teal-dark uppercase">Step 1 · File</span>
          </div>

          <input ref={fileRef} type="file" accept=".csv,.xlsx,.xls,.txt" className="hidden" onChange={(e) => { setFile(e.target.files?.[0] ?? null); setResult(null); setError(null) }} />

          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            className={`group flex flex-1 items-center justify-center gap-3 rounded-2xl border-2 border-dashed px-4 py-5 text-center transition-colors ${file ? 'border-green-300 bg-green-50/50 hover:border-green-400' : 'border-slate-200 bg-slate-50/70 hover:border-brand-teal hover:bg-brand-teal/[0.04]'}`}
          >
            {file ? (
              <>
                <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-green-500 text-white"><Check size={18} /></span>
                <div className="min-w-0 text-left">
                  <div className="truncate font-display text-sm font-bold text-navy-900">{file.name}</div>
                  <div className="text-xs text-slate-500">{(file.size / 1024).toFixed(1)} KB · click to change</div>
                </div>
              </>
            ) : (
              <>
                <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-white text-brand-teal-dark shadow-sm ring-1 ring-slate-200 transition-transform group-hover:scale-105">
                  <FileSpreadsheet size={18} />
                </span>
                <div className="text-left">
                  <div className="font-display text-sm font-bold text-navy-900">Choose a CSV or Excel file</div>
                  <div className="text-xs text-slate-500">.csv, .xlsx, .xls, .txt</div>
                </div>
              </>
            )}
          </button>

          {file && (
            <button className="mt-2 self-start text-xs font-semibold text-red-500 hover:underline" onClick={resetAll}>
              Remove file
            </button>
          )}
        </div>

        <div className="flex flex-col rounded-2xl border border-slate-200 bg-white p-4">
          <div className="mb-2.5 flex items-center gap-2">
            <span className="rounded-lg bg-brand-teal/10 px-2 py-0.5 font-display text-[11px] font-bold tracking-wider text-brand-teal-dark uppercase">Step 2 · Send</span>
          </div>

          <Field label="Template">
            <select className={selectCls} value={templateId} onChange={(e) => setTemplateId(e.target.value)}>
              <option value="">— select —</option>
              {templates.data?.map((t) => (
                <option key={t.id} value={t.id}>{t.name}</option>
              ))}
            </select>
          </Field>

          <Button
            className="mt-auto w-full"
            disabled={!ready || uploadMutation.isPending}
            icon={<Send size={15} />}
            onClick={() => uploadMutation.mutate()}
          >
            {uploadMutation.isPending ? 'Sending…' : 'Send via SMTP'}
          </Button>
        </div>
      </div>

      {error && <div className="mt-3 rounded-xl border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-600">⚠ {error}</div>}
      {result && (
        <div className="mt-3 rounded-xl border border-green-200 bg-green-50 p-3 text-sm text-green-700">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="font-display font-bold">{result.valid_rows} queued · {result.invalid_rows} invalid · {result.total_rows} total</div>
            <Badge tone="green">queued</Badge>
          </div>
          <div className="mt-1 text-xs">{result.unsubscribed_rows > 0 ? `${result.unsubscribed_rows} unsubscribed skipped · ` : ''}auto-sends 1-by-1, 1s apart</div>
          {result.errors?.length > 0 && (
            <ul className="mt-2 max-h-24 list-inside list-disc space-y-0.5 overflow-y-auto text-xs">{result.errors.map((e: string, i: number) => <li key={i}>{e}</li>)}</ul>
          )}
        </div>
      )}

      {!file && !result && (
        <p className="mt-3 flex items-center gap-1.5 text-xs text-slate-400">
          <AlertTriangle size={13} /> Pick your CSV and hit Send — we push each row through SMTP automatically.
        </p>
      )}
    </Panel>
  )
}

function UnsubscribedTab() {
  const unsub = useQuery({ queryKey: ['email-unsubscribed'], queryFn: emailApi.unsubscribed })

  return (
    <Panel className="scroll-fade">
      <h2 className="mb-4 flex items-center gap-2 font-display text-sm font-bold tracking-wide text-navy-900 uppercase">
        <UserMinus size={15} className="text-brand-teal" /> Unsubscribed ({unsub.data?.total ?? 0})
      </h2>
      {unsub.isLoading ? <Spinner label="Loading" /> : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-slate-100 bg-slate-50/80 font-display text-[11px] font-bold tracking-widest text-slate-500 uppercase">
                <th className="px-4 py-3">Email</th>
                <th className="px-4 py-3">Source</th>
                <th className="px-4 py-3 text-right">Date</th>
              </tr>
            </thead>
            <tbody>
              {unsub.data?.items.map((u) => (
                <tr key={u.id} className="border-b border-slate-50 last:border-0">
                  <td className="px-4 py-3 font-semibold text-navy-900">{u.email}</td>
                  <td className="px-4 py-3"><Badge tone="neutral">{u.source ?? '—'}</Badge></td>
                  <td className="px-4 py-3 text-right text-xs text-slate-400">{new Date(u.unsubscribed_at).toLocaleString()}</td>
                </tr>
              ))}
              {unsub.data?.items.length === 0 && <tr><td colSpan={3}><EmptyState message="No unsubscribed emails" /></td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  )
}
