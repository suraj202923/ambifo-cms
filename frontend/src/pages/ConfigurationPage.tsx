import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Bell,
  Bot,
  Box,
  CircleDot,
  Cloud,
  FileText,
  FolderOpen,
  Layers,
  Mail,
  Power,
  RefreshCw,
  Save,
  Settings,
  Tag,
  Trash2,
  Users,
  CalendarClock,
  PenLine,
  Plus,
} from 'lucide-react'
import { adminApi, configApi, emailApi } from '../api'
import type { ConfigLookup, SegmentConfig } from '../api/types'
import { Badge, Button, EmptyState, Field, inputCls, PageHead, Panel, selectCls, Spinner } from '../components/ui'
import { EmailMacroPalette } from '../components/EmailMacroPalette'

type CategoryKey =
  | 'smtp' | 'teams' | 'storage' | 'meeting' | 'appurl' | 'ai'
  | 'doctemplate' | 'emailtemplates' | 'status' | 'segment'
  | 'cloud' | 'tags' | 'users' | 'docusign' | 'restart'

const CATEGORIES: { key: CategoryKey; label: string; icon: typeof Settings }[] = [
  { key: 'smtp', label: 'SMTP Configuration', icon: Mail },
  { key: 'teams', label: 'Teams Configuration', icon: Bell },
  { key: 'storage', label: 'Document Media Storage', icon: FolderOpen },
  { key: 'meeting', label: 'Meeting Availability', icon: CalendarClock },
  { key: 'appurl', label: 'Application URL', icon: Box },
  { key: 'ai', label: 'AI Settings', icon: Bot },
  { key: 'doctemplate', label: 'Document Template', icon: FileText },
  { key: 'emailtemplates', label: 'Email Templates', icon: Mail },
  { key: 'status', label: 'Status', icon: CircleDot },
  { key: 'segment', label: 'Segment', icon: Layers },
  { key: 'cloud', label: 'Cloud Operators', icon: Cloud },
  { key: 'tags', label: 'Update Tags', icon: Tag },
  { key: 'users', label: 'Admin Users', icon: Users },
  { key: 'docusign', label: 'DocuSign e-Signature', icon: PenLine },
  { key: 'restart', label: 'Restart Application', icon: Power },
]

export default function ConfigurationPage() {
  const [active, setActive] = useState<CategoryKey>('smtp')

  return (
    <div>
      <PageHead
        title="Configuration"
        subtitle="Manage system settings, integrations and reference data"
      />
      <div className="flex flex-col gap-5 lg:flex-row">
        <aside className="lg:w-60 shrink-0">
          <nav className="scroll-fade brand-card flex flex-row flex-wrap gap-1 overflow-x-auto rounded-2xl border border-slate-200 bg-white p-2 shadow-sm lg:flex-col">
            {CATEGORIES.map((c) => {
              const Icon = c.icon
              const isActive = c.key === active
              return (
                <button
                  key={c.key}
                  onClick={() => setActive(c.key)}
                  className={`flex shrink-0 items-center gap-2 rounded-xl px-3 py-2.5 font-display text-xs font-semibold transition-all lg:w-full ${
                    isActive
                      ? 'bg-gradient-to-r from-brand-teal to-brand-teal-dark text-white shadow-md'
                      : 'text-slate-600 hover:bg-slate-100'
                  }`}
                >
                  <Icon size={15} />
                  <span className="whitespace-nowrap lg:whitespace-normal">{c.label}</span>
                </button>
              )
            })}
          </nav>
        </aside>

        <div className="scroll-fade flex-1 min-w-0" key={active}>
          {active === 'smtp' && <SmtpConfig />}
          {active === 'teams' && <TeamsConfig />}
          {active === 'storage' && <StorageConfig />}
          {active === 'meeting' && <MeetingConfig />}
          {active === 'appurl' && <AppUrlConfig />}
          {active === 'ai' && <AiConfig />}
          {active === 'doctemplate' && <DocTemplateConfig />}
          {active === 'emailtemplates' && <EmailTemplatesConfig />}
          {active === 'status' && <LookupConfig title="Deal Statuses" kind="status" />}
          {active === 'segment' && <SegmentConfig />}
          {active === 'cloud' && <LookupConfig title="Cloud Operators" kind="cloud" />}
          {active === 'tags' && <LookupConfig title="Update Tags" kind="tags" colorEditable />}
          {active === 'users' && <UsersConfig />}
          {active === 'docusign' && <DocusignConfig />}
          {active === 'restart' && <RestartConfig />}
        </div>
      </div>
    </div>
  )
}

function ConfigPanel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Panel>
      <div className="mb-4 flex items-center gap-2">
        <Settings size={15} className="text-brand-teal" />
        <h2 className="font-display text-sm font-bold tracking-wide text-navy-900 uppercase">{title}</h2>
      </div>
      {children}
    </Panel>
  )
}

function useSettingQuery<T>(key: string[], fn: () => Promise<T>) {
  return useQuery<T>({ queryKey: key, queryFn: fn })
}

// ------------------------------------------------------------------ SMTP
function SmtpConfig() {
  const qc = useQueryClient()
  const settings = useSettingQuery(['email-settings'], emailApi.settings)
  const [form, setForm] = useState<Record<string, any>>({})
  const data = settings.data

  const save = useMutation({
    mutationFn: () =>
      emailApi.updateSettings({
        smtp_host: (form.smtp_host ?? data?.smtp_host) as string,
        smtp_port: Number(form.smtp_port ?? data?.smtp_port),
        smtp_username: (form.smtp_username ?? data?.smtp_username) as string,
        smtp_password: form.smtp_password as string | null,
        smtp_use_tls: form.smtp_use_tls ?? data?.smtp_use_tls ?? true,
        smtp_mail_from: (form.smtp_mail_from ?? data?.smtp_mail_from) as string,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['email-settings'] })
      setForm({})
    },
  })

  const test = useMutation({ mutationFn: (to: string) => emailApi.testSmtp(to) })
  const [testTo, setTestTo] = useState('')

  const f = (k: string) => (k in form ? form[k] : data ? (data as any)[k] : '')
  const set = (k: string, v: any) => setForm((p) => ({ ...p, [k]: v }))

  return (
    <ConfigPanel title="SMTP Configuration">
      {settings.isLoading ? (
        <Spinner label="Loading settings" />
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="SMTP Host"><input className={inputCls} value={f('smtp_host')} onChange={(e) => set('smtp_host', e.target.value)} /></Field>
          <Field label="Port"><input type="number" className={inputCls} value={f('smtp_port')} onChange={(e) => set('smtp_port', e.target.value)} /></Field>
          <Field label="Username"><input className={inputCls} value={f('smtp_username')} onChange={(e) => set('smtp_username', e.target.value)} /></Field>
          <Field label="Password"><input type="password" className={inputCls} value={f('smtp_password')} onChange={(e) => set('smtp_password', e.target.value)} placeholder={data?.smtp_password_set ? '(already set)' : ''} /></Field>
          <Field label="Mail From"><input className={inputCls} value={f('smtp_mail_from')} onChange={(e) => set('smtp_mail_from', e.target.value)} /></Field>
          <Field label="Use TLS">
            <select className={selectCls} value={String(f('smtp_use_tls'))} onChange={(e) => set('smtp_use_tls', e.target.value === 'true')}>
              <option value="true">Yes</option>
              <option value="false">No</option>
            </select>
          </Field>
        </div>
      )}
      <div className="mt-5 flex flex-wrap items-center gap-3">
        <Button icon={<Save size={15} />} onClick={() => save.mutate()} disabled={save.isPending || settings.isLoading}>
          {save.isPending ? 'Saving…' : 'Save SMTP'}
        </Button>
        <div className="flex items-center gap-2">
          <input className={`${inputCls} w-56`} value={testTo} onChange={(e) => setTestTo(e.target.value)} placeholder="test@example.com" />
          <Button variant="outline" onClick={() => testTo.trim() && test.mutate(testTo.trim())} disabled={!testTo.trim() || test.isPending}>
            {test.isPending ? 'Sending…' : 'Send test'}
          </Button>
        </div>
      </div>
      {test.isSuccess && <div className="mt-3 rounded-xl border border-green-200 bg-green-50 px-4 py-2 text-sm text-green-700">{test.data.ok ? 'Test email sent.' : `Status: ${test.data.status}`}</div>}
      {test.isError && <div className="mt-3 rounded-xl border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-600">Test failed: {(test.error as Error).message}</div>}
    </ConfigPanel>
  )
}

// ------------------------------------------------------------------ Teams
function TeamsConfig() {
  const qc = useQueryClient()
  const query = useSettingQuery(['config-teams'], configApi.teams)
  const [form, setForm] = useState<Record<string, any>>({})
  const save = useMutation({
    mutationFn: () => configApi.updateTeams({
      webhook_url: (form.webhook_url ?? query.data?.webhook_url ?? '') as string,
      enabled: form.enabled ?? query.data?.enabled ?? true,
    }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['config-teams'] }); setForm({}) },
  })
  const f = (k: string) => (k in form ? form[k] : query.data ? (query.data as any)[k] : '')
  const set = (k: string, v: any) => setForm((p) => ({ ...p, [k]: v }))
  return (
    <ConfigPanel title="Teams Configuration">
      <p className="mb-4 text-sm text-slate-500">Send notifications to a Microsoft Teams channel via an incoming webhook.</p>
      <Field label="Teams Webhook URL"><input className={inputCls} value={f('webhook_url')} onChange={(e) => set('webhook_url', e.target.value)} placeholder="https://outlook.office.com/webhook/..." /></Field>
      <Field label="Enable notifications">
        <select className={selectCls} value={String(!!f('enabled'))} onChange={(e) => set('enabled', e.target.value === 'true')}>
          <option value="true">Enabled</option>
          <option value="false">Disabled</option>
        </select>
      </Field>
      <div className="mt-5"><Button icon={<Save size={15} />} disabled={save.isPending} onClick={() => save.mutate()}>{save.isPending ? 'Saving…' : 'Save Teams config'}</Button></div>
    </ConfigPanel>
  )
}

// ------------------------------------------------------------------ Storage
function StorageConfig() {
  const qc = useQueryClient()
  const query = useSettingQuery(['config-storage'], configApi.storage)
  const [form, setForm] = useState<Record<string, any>>({})
  const save = useMutation({
    mutationFn: () => configApi.updateStorage({
      backend: (form.backend ?? query.data?.backend ?? 'local') as string,
      docs_dir: (form.docs_dir ?? query.data?.docs_dir ?? 'storage/documents') as string,
      max_upload_mb: Number(form.max_upload_mb ?? query.data?.max_upload_mb ?? 100),
      onedrive_folder_link: (form.onedrive_folder_link ?? query.data?.onedrive_folder_link ?? '') as string,
    }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['config-storage'] }); setForm({}) },
  })
  const f = (k: string) => (k in form ? form[k] : query.data ? (query.data as any)[k] : '')
  const set = (k: string, v: any) => setForm((p) => ({ ...p, [k]: v }))
  const isOneDrive = f('backend') === 'onedrive'
  return (
    <ConfigPanel title="Document Media Storage">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field label="Storage backend"><select className={selectCls} value={f('backend')} onChange={(e) => set('backend', e.target.value)}><option value="local">Local</option><option value="onedrive">OneDrive (link)</option><option value="s3">S3 (future)</option></select></Field>
        <Field label="Max upload (MB)"><input type="number" className={inputCls} value={f('max_upload_mb')} onChange={(e) => set('max_upload_mb', e.target.value)} /></Field>
        {isOneDrive ? (
          <Field label="OneDrive folder link">
            <input className={inputCls} value={f('onedrive_folder_link')} onChange={(e) => set('onedrive_folder_link', e.target.value)} placeholder="https://…sharepoint.com/:f:/…?e=…" />
          </Field>
        ) : (
          <Field label="Documents directory" ><input className={inputCls} value={f('docs_dir')} onChange={(e) => set('docs_dir', e.target.value)} /></Field>
        )}
      </div>
      <div className="mt-5"><Button icon={<Save size={15} />} disabled={save.isPending} onClick={() => save.mutate()}>{save.isPending ? 'Saving…' : 'Save storage config'}</Button></div>
    </ConfigPanel>
  )
}

// ------------------------------------------------------------------ Meeting
function MeetingConfig() {
  const qc = useQueryClient()
  const query = useSettingQuery(['config-meeting'], configApi.meetingAvailability)
  const [form, setForm] = useState<Record<string, any>>({})
  const save = useMutation({
    mutationFn: () => configApi.updateMeetingAvailability({
      default_duration_min: Number(form.default_duration_min ?? query.data?.default_duration_min ?? 30),
      default_expiry_days: Number(form.default_expiry_days ?? query.data?.default_expiry_days ?? 7),
    }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['config-meeting'] }); setForm({}) },
  })
  const f = (k: string) => (k in form ? form[k] : query.data ? (query.data as any)[k] : '')
  const set = (k: string, v: any) => setForm((p) => ({ ...p, [k]: v }))
  return (
    <ConfigPanel title="Meeting Availability">
      <p className="mb-4 text-sm text-slate-500">Defaults used when creating meeting availability requests.</p>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field label="Default duration (min)"><input type="number" className={inputCls} value={f('default_duration_min')} onChange={(e) => set('default_duration_min', e.target.value)} /></Field>
        <Field label="Link expiry (days)"><input type="number" className={inputCls} value={f('default_expiry_days')} onChange={(e) => set('default_expiry_days', e.target.value)} /></Field>
      </div>
      <div className="mt-5"><Button icon={<Save size={15} />} disabled={save.isPending} onClick={() => save.mutate()}>{save.isPending ? 'Saving…' : 'Save meeting config'}</Button></div>
    </ConfigPanel>
  )
}

// ------------------------------------------------------------------ App URL
function AppUrlConfig() {
  const qc = useQueryClient()
  const query = useSettingQuery(['config-appurl'], configApi.appUrl)
  const [form, setForm] = useState<Record<string, any>>({})
  const save = useMutation({
    mutationFn: () => configApi.updateAppUrl({
      base_url: ((form.base_url ?? query.data?.base_url ?? '') as string).trim(),
    }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['config-appurl'] }); setForm({}) },
  })
  const f = (k: string) => (k in form ? form[k] : query.data ? (query.data as any)[k] : '')
  const set = (k: string, v: any) => setForm((p) => ({ ...p, [k]: v }))
  return (
    <ConfigPanel title="Application URL">
      <p className="mb-4 text-sm text-slate-500">Base URL used to build public links (e.g. email unsubscribe).</p>
      <Field label="App base URL"><input className={inputCls} value={f('base_url')} onChange={(e) => set('base_url', e.target.value)} placeholder="http://127.0.0.1:8000" /></Field>
      <div className="mt-5"><Button icon={<Save size={15} />} disabled={save.isPending || !f('base_url')} onClick={() => save.mutate()}>{save.isPending ? 'Saving…' : 'Save URL'}</Button></div>
    </ConfigPanel>
  )
}

// ------------------------------------------------------------------ AI
function AiConfig() {
  const qc = useQueryClient()
  const query = useSettingQuery(['config-ai'], configApi.ai)
  const [form, setForm] = useState<Record<string, any>>({})
  const save = useMutation({
    mutationFn: () => configApi.updateAi({
      provider: (form.provider ?? query.data?.provider ?? 'openai') as string,
      model: (form.model ?? query.data?.model ?? '') as string,
      max_tokens: Number(form.max_tokens ?? query.data?.max_tokens ?? 2048),
      api_key: form.api_key as string | undefined,
    }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['config-ai'] }); setForm({}) },
  })
  const f = (k: string) => (k in form ? form[k] : query.data ? (query.data as any)[k] : '')
  const set = (k: string, v: any) => setForm((p) => ({ ...p, [k]: v }))
  return (
    <ConfigPanel title="AI Settings">
      <p className="mb-4 text-sm text-slate-500">Optional defaults for AI generation. Leave API key blank to keep the current key.</p>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field label="Provider"><select className={selectCls} value={f('provider')} onChange={(e) => set('provider', e.target.value)}><option value="openai">OpenAI</option><option value="gemini">Google Gemini</option></select></Field>
        <Field label="Default model"><input className={inputCls} value={f('model')} onChange={(e) => set('model', e.target.value)} placeholder="gpt-4o / gemini-1.5-pro" /></Field>
        <Field label="Max tokens"><input type="number" className={inputCls} value={f('max_tokens')} onChange={(e) => set('max_tokens', e.target.value)} /></Field>
        <Field label="API key"><input type="password" className={inputCls} value={f('api_key')} onChange={(e) => set('api_key', e.target.value)} placeholder={query.data?.api_key_set ? '(already set)' : ''} /></Field>
      </div>
      <div className="mt-5"><Button icon={<Save size={15} />} disabled={save.isPending} onClick={() => save.mutate()}>{save.isPending ? 'Saving…' : 'Save AI config'}</Button></div>
    </ConfigPanel>
  )
}

// ------------------------------------------------------------------ DocuSign
function DocusignConfig() {
  const qc = useQueryClient()
  const query = useSettingQuery(['config-docusign'], configApi.docusign)
  const [form, setForm] = useState<Record<string, any>>({})
  const save = useMutation({
    mutationFn: () => configApi.updateDocusign({
      integration_key: (form.integration_key ?? query.data?.integration_key ?? '') as string,
      account_id: (form.account_id ?? query.data?.account_id ?? '') as string,
      base_url: (form.base_url ?? query.data?.base_url ?? 'https://demo.docusign.net') as string,
      enabled: form.enabled ?? query.data?.enabled ?? false,
      private_key: form.private_key as string | undefined,
    }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['config-docusign'] }); setForm({}) },
  })
  const f = (k: string) => (k in form ? form[k] : query.data ? (query.data as any)[k] : '')
  const set = (k: string, v: any) => setForm((p) => ({ ...p, [k]: v }))
  return (
    <ConfigPanel title="DocuSign e-Signature">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field label="Integration key"><input className={inputCls} value={f('integration_key')} onChange={(e) => set('integration_key', e.target.value)} /></Field>
        <Field label="Account ID"><input className={inputCls} value={f('account_id')} onChange={(e) => set('account_id', e.target.value)} /></Field>
        <Field label="Base URL"><input className={inputCls} value={f('base_url')} onChange={(e) => set('base_url', e.target.value)} /></Field>
        <Field label="Enabled"><select className={selectCls} value={String(!!f('enabled'))} onChange={(e) => set('enabled', e.target.value === 'true')}><option value="true">Enabled</option><option value="false">Disabled</option></select></Field>
        <div className="sm:col-span-2"><Field label="Private key"><textarea className={`${inputCls} min-h-[80px] font-mono`} value={f('private_key')} onChange={(e) => set('private_key', e.target.value)} placeholder={query.data?.private_key_set ? '(already set - paste to replace)' : 'Paste RSA private key'} /></Field></div>
      </div>
      <div className="mt-5"><Button icon={<Save size={15} />} disabled={save.isPending} onClick={() => save.mutate()}>{save.isPending ? 'Saving…' : 'Save DocuSign config'}</Button></div>
    </ConfigPanel>
  )
}

// ------------------------------------------------------------------ Restart
function RestartConfig() {
  const qc = useQueryClient()
  const [confirming, setConfirming] = useState(false)
  const restart = useMutation({
    mutationFn: () => configApi.restart().then((r) => r),
    onSuccess: () => {
      qc.clear()
    },
  })
  return (
    <ConfigPanel title="Restart Application">
      <p className="mb-4 text-sm text-slate-500">Restart the backend API process. The supervisor (start-crm.ps1 / uvicorn) will bring it back up automatically.</p>
      <div className="flex items-center gap-3">
        {confirming ? (
          <>
            <Button variant="outline" onClick={() => setConfirming(false)}>Cancel</Button>
            <Button icon={<RefreshCw size={15} />} disabled={restart.isPending} onClick={() => restart.mutate()}>
              {restart.isPending ? 'Restarting…' : 'Confirm restart'}
            </Button>
          </>
        ) : (
          <Button icon={<Power size={15} />} onClick={() => setConfirming(true)}>Restart application</Button>
        )}
      </div>
      {restart.isSuccess && <div className="mt-3 rounded-xl border border-green-200 bg-green-50 px-4 py-2 text-sm text-green-700">Restart initiated.</div>}
    </ConfigPanel>
  )
}

// ------------------------------------------------------------------ Generic Lookup CRUD (status / cloud / tags)
function LookupConfig({ title, kind, colorEditable = false }: { title: string; kind: 'status' | 'cloud' | 'tags'; colorEditable?: boolean }) {
  const qc = useQueryClient()
  const key = kind === 'status' ? 'config-statuses' : kind === 'cloud' ? 'config-cloud' : 'config-tags'
  const listFn = kind === 'status' ? configApi.statuses : kind === 'cloud' ? configApi.cloudOperators : configApi.updateTags
  const createFn = kind === 'status' ? configApi.createStatus : kind === 'cloud' ? configApi.createCloudOperator : configApi.createUpdateTag
  const updateFn = kind === 'status' ? configApi.updateStatus : kind === 'cloud' ? configApi.updateCloudOperator : configApi.updateUpdateTag
  const deleteFn = kind === 'status' ? configApi.deleteStatus : kind === 'cloud' ? configApi.deleteCloudOperator : configApi.deleteUpdateTag

  const query = useQuery({ queryKey: [key], queryFn: listFn })
  const [name, setName] = useState('')
  const [color, setColor] = useState('#8a8f98')
  const [editing, setEditing] = useState<ConfigLookup | null>(null)
  const [editName, setEditName] = useState('')
  const [editColor, setEditColor] = useState('#8a8f98')

  const create = useMutation({
    mutationFn: () => (colorEditable ? createFn({ name, color } as never) : createFn({ name } as never)),
    onSuccess: () => { qc.invalidateQueries({ queryKey: [key] }); setName(''); setColor('#8a8f98') },
  })
  const del = useMutation({
    mutationFn: (id: number) => deleteFn(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: [key] }); qc.invalidateQueries({ queryKey: ['lookups'] }) },
  })
  const saveEdit = useMutation({
    mutationFn: () => updateFn(editing!.id, colorEditable ? { name: editName, color: editColor } : { name: editName } as never),
    onSuccess: () => { qc.invalidateQueries({ queryKey: [key] }); qc.invalidateQueries({ queryKey: ['lookups'] }); setEditing(null) },
  })

  return (
    <ConfigPanel title={title}>
      <div className="mb-5 flex flex-wrap items-end gap-3">
        <Field label="Name"><input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} placeholder="New value" /></Field>
        {colorEditable && (
          <Field label="Color"><input type="color" className="h-10 w-16 rounded-lg border border-slate-200" value={color} onChange={(e) => setColor(e.target.value)} /></Field>
        )}
        <Button icon={<Plus size={15} />} disabled={!name.trim() || create.isPending} onClick={() => create.mutate()}>Add</Button>
      </div>
      {query.isLoading ? <Spinner label="Loading" /> : (
        <div className="space-y-2">
          {query.data?.length === 0 && <EmptyState message="Nothing configured yet" />}
          {query.data?.map((item: ConfigLookup) => (
            <div key={item.id} className="flex items-center gap-3 rounded-xl border border-slate-100 bg-slate-50/50 px-4 py-2.5">
              {editing?.id === item.id ? (
                <>
                  <input className={`${inputCls} flex-1`} value={editName} onChange={(e) => setEditName(e.target.value)} />
                  {colorEditable && <input type="color" className="h-9 w-12 rounded-lg border border-slate-200" value={editColor} onChange={(e) => setEditColor(e.target.value)} />}
                  <Button onClick={() => saveEdit.mutate()} disabled={saveEdit.isPending}>Save</Button>
                  <Button variant="ghost" onClick={() => setEditing(null)}>Cancel</Button>
                </>
              ) : (
                <>
                  <span className="h-3 w-3 rounded-full" style={{ background: item.color ?? '#8a8f98' }} />
                  <span className="flex-1 text-sm font-medium text-navy-900">{item.name}</span>
                  {item.is_active === false && <Badge tone="neutral">inactive</Badge>}
                  <button
                    type="button"
                    className="rounded-lg p-1.5 text-slate-400 hover:bg-brand-teal/10 hover:text-brand-teal-dark"
                    onClick={() => { setEditing(item); setEditName(item.name); setEditColor(item.color ?? '#8a8f98') }}
                    title="Edit"
                  >
                    <PenLine size={14} />
                  </button>
                  <button type="button" className="rounded-lg p-1.5 text-slate-400 hover:bg-red-50 hover:text-red-600" onClick={() => del.mutate(item.id)} title="Delete"><Trash2 size={14} /></button>
                </>
              )}
            </div>
          ))}
        </div>
      )}
    </ConfigPanel>
  )
}

// ------------------------------------------------------------------ Segment CRUD (with credit fields)
function SegmentConfig() {
  const qc = useQueryClient()
  const query = useQuery({ queryKey: ['config-segments'], queryFn: configApi.segments })
  const EMPTY: Partial<SegmentConfig> = { name: '', credit_basis_mrr: true, credit_basis_arr: false, credit_on_arr: false }
  const [form, setForm] = useState<Partial<SegmentConfig>>(EMPTY)
  const [editing, setEditing] = useState<SegmentConfig | null>(null)

  const create = useMutation({
    mutationFn: () => configApi.createSegment({ ...EMPTY, ...form }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['config-segments'] }); setForm(EMPTY); qc.invalidateQueries({ queryKey: ['lookups'] }) },
  })
  const del = useMutation({
    mutationFn: (id: number) => configApi.deleteSegment(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['config-segments'] }); qc.invalidateQueries({ queryKey: ['lookups'] }) },
  })

  const fld = (k: keyof SegmentConfig) =>
    editing ? (editing[k] as any) ?? '' : (form[k] as any) ?? ''
  const set = (k: keyof SegmentConfig, v: any) => editing ? setEditing((e) => ({ ...e!, [k]: v })) : setForm((p) => ({ ...p, [k]: v }))

  return (
    <ConfigPanel title="Segments">
      <div className="mb-5 grid grid-cols-1 gap-3 rounded-2xl border border-slate-100 bg-slate-50/50 p-4 sm:grid-cols-4">
        <Field label="Name"><input className={inputCls} value={fld('name')} onChange={(e) => set('name', e.target.value)} /></Field>
        <Field label="Credit %"><input type="number" className={inputCls} value={fld('credit_percentage') ?? ''} onChange={(e) => set('credit_percentage', e.target.value === '' ? null : Number(e.target.value))} /></Field>
        <Field label="Credit % (customer)"><input type="number" className={inputCls} value={fld('credit_percentage_customer') ?? ''} onChange={(e) => set('credit_percentage_customer', e.target.value === '' ? null : Number(e.target.value))} /></Field>
        <Field label="Credit % (Ambifo)"><input type="number" className={inputCls} value={fld('credit_percentage_ambifo') ?? ''} onChange={(e) => set('credit_percentage_ambifo', e.target.value === '' ? null : Number(e.target.value))} /></Field>
        <label className="flex items-center gap-2 text-sm font-medium text-navy-700"><input type="checkbox" className="h-4 w-4 accent-brand-teal" checked={!!fld('credit_basis_mrr')} onChange={(e) => set('credit_basis_mrr', e.target.checked)} /> Basis: MRR</label>
        <label className="flex items-center gap-2 text-sm font-medium text-navy-700"><input type="checkbox" className="h-4 w-4 accent-brand-teal" checked={!!fld('credit_basis_arr')} onChange={(e) => set('credit_basis_arr', e.target.checked)} /> Basis: ARR</label>
        <label className="flex items-center gap-2 text-sm font-medium text-navy-700"><input type="checkbox" className="h-4 w-4 accent-brand-teal" checked={!!fld('credit_on_arr')} onChange={(e) => set('credit_on_arr', e.target.checked)} /> Credit on ARR</label>
        <div className="flex items-end gap-2 sm:col-span-4">
          {editing ? (
            <>
              <Button
                onClick={() => {
                  configApi.updateSegment(editing.id, editing).then(() => { qc.invalidateQueries({ queryKey: ['config-segments'] }); qc.invalidateQueries({ queryKey: ['lookups'] }); setEditing(null) })
                }}
              >Save changes</Button>
              <Button variant="ghost" onClick={() => setEditing(null)}>Cancel</Button>
            </>
          ) : (
            <Button icon={<Plus size={15} />} disabled={!form.name || create.isPending} onClick={() => create.mutate()}>Add segment</Button>
          )}
        </div>
      </div>

      {query.isLoading ? <Spinner label="Loading" /> : (
        <div className="space-y-2">
          {query.data?.length === 0 && <EmptyState message="No segments configured" />}
          {query.data?.map((s: SegmentConfig) => (
            <div key={s.id} className="flex items-center gap-3 rounded-xl border border-slate-100 bg-slate-50/50 px-4 py-2.5">
              <span className="flex-1 text-sm font-medium text-navy-900">{s.name}</span>
              <Badge tone="teal">{s.credit_basis_mrr ? 'MRR' : s.credit_basis_arr ? 'ARR' : '—'}</Badge>
              {s.is_active === false && <Badge tone="neutral">inactive</Badge>}
              <button type="button" className="rounded-lg p-1.5 text-slate-400 hover:bg-brand-teal/10 hover:text-brand-teal-dark" onClick={() => { setEditing({ ...s }); setForm({}) }} title="Edit"><PenLine size={14} /></button>
              <button type="button" className="rounded-lg p-1.5 text-slate-400 hover:bg-red-50 hover:text-red-600" onClick={() => del.mutate(s.id)} title="Delete"><Trash2 size={14} /></button>
            </div>
          ))}
        </div>
      )}
    </ConfigPanel>
  )
}

// ------------------------------------------------------------------ Email templates
function EmailTemplatesConfig() {
  const qc = useQueryClient()
  const templates = useQuery({ queryKey: ['email-templates'], queryFn: emailApi.templates })
  const [name, setName] = useState('')
  const [subject, setSubject] = useState('')
  const [body, setBody] = useState('')
  const [editing, setEditing] = useState<any | null>(null)

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
    if (target === 'subject') setSubject(next)
    else setBody(next)
    requestAnimationFrame(() => {
      const pos = start + macro.length
      field.focus()
      field.setSelectionRange(pos, pos)
    })
    setActiveField(target)
  }

  const save = useMutation({
    mutationFn: () => editing
      ? emailApi.updateTemplate(editing.id, { name, subject_template: subject, body_template: body })
      : emailApi.createTemplate({ name, subject_template: subject, body_template: body, is_active: true }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['email-templates'] })
      setName(''); setSubject(''); setBody(''); setEditing(null)
    },
  })
  const del = useMutation({
    mutationFn: (id: number) => emailApi.deleteTemplate(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['email-templates'] }),
  })

  return (
    <ConfigPanel title="Email Templates">
      <div className="mb-5 space-y-3 rounded-2xl border border-slate-100 bg-slate-50/50 p-4">
        <h3 className="font-display text-xs font-bold tracking-widest text-slate-500 uppercase">{editing ? 'Edit template' : 'New template'}</h3>
        <Field label="Name"><input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <Field label="Subject template"><input ref={subjectRef} className={inputCls} value={subject} onChange={(e) => setSubject(e.target.value)} onFocus={() => setActiveField('subject')} /></Field>
        <Field label="Body template"><textarea ref={bodyRef} className={`${inputCls} min-h-[100px] font-mono text-xs`} value={body} onChange={(e) => setBody(e.target.value)} onFocus={() => setActiveField('body')} /></Field>
        <EmailMacroPalette onInsert={insertMacro} />
        <div className="flex gap-2">
          <Button icon={<Save size={15} />} disabled={!name.trim() || save.isPending} onClick={() => save.mutate()}>{save.isPending ? 'Saving…' : editing ? 'Save changes' : 'Create template'}</Button>
          {editing && <Button variant="ghost" onClick={() => setEditing(null)}>Cancel</Button>}
        </div>
      </div>
      {templates.isLoading ? <Spinner label="Loading" /> : (
        <div className="space-y-2">
          {templates.data?.map((t: any) => (
            <div key={t.id} className="flex items-center gap-3 rounded-xl border border-slate-100 bg-slate-50/50 px-4 py-2.5">
              <FileText size={15} className="shrink-0 text-brand-teal" />
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-medium text-navy-900">{t.name}</div>
                <div className="truncate text-xs text-slate-400">{t.subject_template}</div>
              </div>
              <button type="button" className="rounded-lg p-1.5 text-slate-400 hover:bg-brand-teal/10 hover:text-brand-teal-dark" onClick={() => { setEditing(t); setName(t.name); setSubject(t.subject_template); setBody(t.body_template) }} title="Edit"><PenLine size={14} /></button>
              <button type="button" className="rounded-lg p-1.5 text-slate-400 hover:bg-red-50 hover:text-red-600" onClick={() => del.mutate(t.id)} title="Delete"><Trash2 size={14} /></button>
            </div>
          ))}
        </div>
      )}
    </ConfigPanel>
  )
}

// ------------------------------------------------------------------ Document template (SOW master template placeholder)
function DocTemplateConfig() {
  return (
    <ConfigPanel title="Document Template">
      <p className="text-sm text-slate-500">
        Document (SOW) templates are generated by the Rust engine. Template authoring for master SOW sections is coming soon.
      </p>
      <EmptyState message="No SOW master templates configured" />
    </ConfigPanel>
  )
}

// ------------------------------------------------------------------ Admin users
function UsersConfig() {
  const qc = useQueryClient()
  const users = useQuery({ queryKey: ['admin-users'], queryFn: adminApi.users })
  const [form, setForm] = useState<{ username: string; email: string; password: string; full_name: string; is_admin: boolean }>({ username: '', email: '', password: '', full_name: '', is_admin: false })

  const create = useMutation({
    mutationFn: () => adminApi.createUser({ username: form.username, email: form.email, password: form.password, full_name: form.full_name || null, is_admin: form.is_admin }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['admin-users'] }); setForm({ username: '', email: '', password: '', full_name: '', is_admin: false }) },
  })
  const toggle = useMutation({
    mutationFn: ({ id, is_active }: { id: number; is_active: boolean }) => adminApi.updateUser(id, { is_active }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-users'] }),
  })

  return (
    <ConfigPanel title="Admin Users">
      <div className="mb-5 grid grid-cols-1 gap-3 rounded-2xl border border-slate-100 bg-slate-50/50 p-4 sm:grid-cols-2">
        <Field label="Username"><input className={inputCls} value={form.username} onChange={(e) => setForm((f) => ({ ...f, username: e.target.value }))} /></Field>
        <Field label="Email"><input className={inputCls} value={form.email} onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))} /></Field>
        <Field label="Full name"><input className={inputCls} value={form.full_name} onChange={(e) => setForm((f) => ({ ...f, full_name: e.target.value }))} /></Field>
        <Field label="Password"><input type="password" className={inputCls} value={form.password} onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))} /></Field>
        <label className="flex items-center gap-2 text-sm font-medium text-navy-700"><input type="checkbox" className="h-4 w-4 accent-brand-teal" checked={form.is_admin} onChange={(e) => setForm((f) => ({ ...f, is_admin: e.target.checked }))} /> Admin role</label>
        <div className="flex items-end"><Button icon={<Plus size={15} />} disabled={!form.username || !form.email || !form.password || create.isPending} onClick={() => create.mutate()}>Create user</Button></div>
      </div>
      {users.isLoading ? <Spinner label="Loading" /> : (
        <div className="space-y-2">
          {users.data?.map((u: any) => (
            <div key={u.id} className="flex items-center gap-3 rounded-xl border border-slate-100 bg-slate-50/50 px-4 py-2.5">
              <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-gradient-to-br from-brand-teal to-brand-teal-dark font-display text-xs font-bold text-white">{u.username.slice(0, 1).toUpperCase()}</span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 text-sm font-medium text-navy-900">
                  {u.username}
                  {u.is_admin && <Badge tone="navy">admin</Badge>}
                  {!u.is_active && <Badge tone="neutral">inactive</Badge>}
                </div>
                <div className="truncate text-xs text-slate-400">{u.email}{u.full_name ? ` · ${u.full_name}` : ''}</div>
              </div>
              <button type="button" className={`rounded-lg px-2.5 py-1.5 font-display text-xs font-bold transition-colors ${u.is_active ? 'text-red-500 hover:bg-red-50' : 'text-brand-teal-dark hover:bg-brand-teal/10'}`} onClick={() => toggle.mutate({ id: u.id, is_active: !u.is_active })}>
                {u.is_active ? 'Deactivate' : 'Activate'}
              </button>
            </div>
          ))}
        </div>
      )}
    </ConfigPanel>
  )
}
