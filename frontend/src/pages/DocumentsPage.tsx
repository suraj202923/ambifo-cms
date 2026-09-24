import { useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, ExternalLink, Eye, FileArchive, FileImage, FileSpreadsheet, FileText, Film, FolderUp, Mail, Search, Trash2, Upload, X } from 'lucide-react'
import { customerApi, documentApi } from '../api'
import { Button, Badge, EmptyState, Field, FilePreviewModal, inputCls, PageHead, Panel, selectCls, Spinner, isTextPreview } from '../components/ui'

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

export default function DocumentsPage() {
  const [tab, setTab] = useState<'sow' | 'files'>('sow')

  const TABS = [
    { key: 'sow', label: 'BOM' },
    { key: 'files', label: 'Files' },
  ] as const

  return (
    <div>
      <PageHead title="Documents" subtitle="Engine-generated BOMs and per-customer file storage" />

      <div className="scroll-fade mb-5 flex gap-1 rounded-2xl border border-slate-200 bg-white p-1 shadow-sm w-fit">
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
        {tab === 'sow' ? <SowTab /> : <FilesTab />}
      </div>
    </div>
  )
}

function SowTab() {
  const queryClient = useQueryClient()
  const customers = useQuery({ queryKey: ['customers'], queryFn: () => customerApi.list({ limit: 200 }) })
  const sows = useQuery({ queryKey: ['sows'], queryFn: () => documentApi.sows() })

  const [selected, setSelected] = useState<number | null>(null)

  const [csvFile, setCsvFile] = useState<File | null>(null)
  const [csvCustomerId, setCsvCustomerId] = useState('')
  const [csvError, setCsvError] = useState<string | null>(null)
  const [csvDone, setCsvDone] = useState<string | null>(null)
  const csvRef = useRef<HTMLInputElement>(null)

  const customerName = useMemo(() => {
    const map = new Map<number, string>()
    customers.data?.forEach((c) => map.set(c.id, c.customer_name))
    return (id: number) => map.get(id) ?? `Customer #${id}`
  }, [customers.data])

  const sowKpis = useMemo(() => {
    const list = sows.data ?? []
    return {
      total: list.length,
      drafts: list.filter((s) => s.status === 'draft').length,
      sent: list.filter((s) => s.status === 'sent').length,
      latest: list.length ? formatRelative(list[0].created_at) : '—',
    }
  }, [sows.data])

  const deleteMutation = useMutation({
    mutationFn: (id: number) => documentApi.deleteSow(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sows'] })
      if (selected) setSelected(null)
    },
  })

  const sendEmailMutation = useMutation({
    mutationFn: (id: number) => documentApi.sendSowEmail(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['email-logs'] }),
  })

  const bomMutation = useMutation({
    mutationFn: () => {
      if (!csvFile) throw new Error('Choose a CSV file first')
      return documentApi.generateBom(Number(csvCustomerId), csvFile)
    },
    onSuccess: (doc) => {
      queryClient.invalidateQueries({ queryKey: ['customer-documents'] })
      setCsvDone(`BOM saved to ${customerName(doc.customer_id)}'s documents (${doc.original_filename})`)
      setCsvError(null)
      setCsvFile(null)
      setCsvCustomerId('')
      if (csvRef.current) csvRef.current.value = ''
    },
    onError: (e) => setCsvError(e instanceof Error ? e.message : 'BOM generation failed'),
  })

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
      <Panel className="scroll-fade lg:col-span-1">
        <h2 className="mb-4 flex items-center gap-2 font-display text-sm font-bold tracking-wide text-navy-900 uppercase">
          <FileSpreadsheet size={15} className="text-brand-teal" /> Generate BOM
        </h2>

        <div className="rounded-2xl border border-brand-teal/20 bg-brand-teal/5 p-4">
          <div className="mb-3 font-display text-xs font-bold tracking-wide text-brand-teal-dark uppercase">
            BOM from AWS calculator CSV → Excel
          </div>

          <input
            ref={csvRef}
            type="file"
            accept=".csv,text/csv,text/plain"
            className="hidden"
            onChange={(e) => {
              setCsvDone(null)
              setCsvError(null)
              const f = e.target.files?.[0]
              if (f) setCsvFile(f)
            }}
          />
          {csvFile && (
            <div className="mb-3 flex items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white px-3 py-2">
              <div className="flex min-w-0 items-center gap-2 text-sm">
                <FileSpreadsheet size={15} className="shrink-0 text-brand-teal" />
                <span className="truncate font-semibold text-navy-900">{csvFile.name}</span>
                <span className="text-xs text-slate-400">({(csvFile.size / 1024).toFixed(1)} KB)</span>
              </div>
              <button className="text-slate-400 transition-colors hover:text-red-500" onClick={() => { setCsvFile(null); if (csvRef.current) csvRef.current.value = '' }}>
                <X size={15} />
              </button>
            </div>
          )}
          <Button variant="outline" className="w-full !py-2 text-xs" icon={<Upload size={14} />} onClick={() => csvRef.current?.click()}>
            {csvFile ? 'Replace CSV' : 'Upload AWS calculator CSV'}
          </Button>

          <div className="mt-3">
            <Field label="Customer *">
              <select className={selectCls} value={csvCustomerId} onChange={(e) => { setCsvDone(null); setCsvCustomerId(e.target.value) }}>
                <option value="">— select customer —</option>
                {customers.data?.map((c) => (
                  <option key={c.id} value={c.id}>{c.customer_name}</option>
                ))}
              </select>
            </Field>
          </div>

          {csvError && <div className="mt-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-600">⚠ {csvError}</div>}
          {csvDone && <div className="mt-3 rounded-xl border border-brand-teal/25 bg-brand-teal/10 px-4 py-3 text-sm text-brand-teal-dark">✓ {csvDone}</div>}

          <Button
            className="mt-4 w-full"
            icon={<FileSpreadsheet size={15} />}
            disabled={bomMutation.isPending || !csvFile || !csvCustomerId}
            onClick={() => bomMutation.mutate()}
          >
            {bomMutation.isPending ? 'Generating BOM…' : 'Generate BOM (Excel)'}
          </Button>
        </div>
      </Panel>

      <Panel className="scroll-fade lg:col-span-2" style={{ animationDelay: '0.1s' }}>
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <h2 className="flex items-center gap-2 font-display text-sm font-bold tracking-wide text-navy-900 uppercase">
            <FileText size={15} className="text-brand-teal" /> BOM library
          </h2>
          <div className="flex items-center gap-2">
            {[
              { label: 'Total', value: sowKpis.total, tone: 'text-navy-900' },
              { label: 'Drafts', value: sowKpis.drafts, tone: 'text-amber-600' },
              { label: 'Sent', value: sowKpis.sent, tone: 'text-brand-teal-dark' },
            ].map((k) => (
              <div key={k.label} className="rounded-xl border border-slate-200 bg-slate-50/70 px-3 py-1.5 text-center">
                <div className={`font-display text-lg font-extrabold leading-none ${k.tone}`}>{k.value}</div>
                <div className="mt-0.5 font-display text-[10px] font-bold tracking-widest text-slate-400 uppercase">{k.label}</div>
              </div>
            ))}
          </div>
        </div>
        {sows.isLoading ? (
          <Spinner label="Loading BOMs" />
        ) : (
          <div className="space-y-3">
            {sows.data?.map((s) => (
              <div key={s.id} className="brand-card overflow-hidden rounded-2xl border border-slate-200">
                <button
                  className="flex w-full items-center justify-between gap-3 p-4 text-left"
                  onClick={() => setSelected((cur) => (cur === s.id ? null : s.id))}
                >
                  <div className="flex min-w-0 items-center gap-3">
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-brand-teal to-brand-cyan text-white">
                      <FileText size={16} />
                    </span>
                    <div className="min-w-0">
                      <div className="truncate font-display font-bold text-navy-900">{s.sow_title ?? 'Untitled BOM'}</div>
                      <div className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-xs text-slate-500">
                        <span className="font-medium text-navy-700">{customerName(s.customer_id)}</span>
                        <span className="text-slate-300">·</span>
                        <span>v{s.version}</span>
                        {s.created_by && <><span className="text-slate-300">·</span><span>{s.created_by}</span></>}
                        <span className="text-slate-300">·</span>
                        <span title={new Date(s.created_at).toLocaleString()}>{formatRelative(s.created_at)}</span>
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge tone={s.status === 'draft' ? 'neutral' : s.status === 'sent' ? 'teal' : 'neutral'}>{s.status}</Badge>
                  </div>
                </button>
                {selected === s.id && (
                  <div className="border-t border-slate-100 p-4">
                    <div className="mb-3 flex items-center gap-2">
                      <Button variant="outline" className="!px-3 !py-1.5 text-xs" icon={<Download size={13} />} onClick={() => documentApi.downloadSow(s.id)}>
                        Download
                      </Button>
                      <Button variant="outline" className="!px-3 !py-1.5 text-xs" icon={<Mail size={13} />} disabled={sendEmailMutation.isPending} onClick={() => sendEmailMutation.mutate(s.id)}>
                        {sendEmailMutation.isPending ? 'Sending…' : 'Email to customer'}
                      </Button>
                      <Button variant="ghost" className="!px-3 !py-1.5 text-xs text-red-500" icon={<Trash2 size={13} />} onClick={() => { if (confirm('Delete this BOM?')) deleteMutation.mutate(s.id) }}>
                        Delete
                      </Button>
                    </div>
                    <iframe title={s.sow_title ?? 'BOM'} srcDoc={s.content_html ?? ''} className="h-80 w-full rounded-xl border border-slate-200 bg-white" />
                  </div>
                )}
              </div>
            ))}
            {sows.data?.length === 0 && <EmptyState message="No BOMs generated yet" />}
          </div>
        )}
      </Panel>
    </div>
  )
}

function FilesTab() {
  const queryClient = useQueryClient()
  const fileRef = useRef<HTMLInputElement>(null)
  const customers = useQuery({ queryKey: ['customers'], queryFn: () => customerApi.list({ limit: 200 }) })
  const docs = useQuery({ queryKey: ['customer-documents'], queryFn: () => documentApi.list() })

  const [customerId, setCustomerId] = useState('')
  const [description, setDescription] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [preview, setPreview] = useState<{
    filename: string
    content?: string | null
    blobUrl?: string | null
    loading: boolean
    error?: string | null
  } | null>(null)

  const customerName = useMemo(() => {
    const map = new Map<number, string>()
    customers.data?.forEach((c) => map.set(c.id, c.customer_name))
    return (id: number) => map.get(id) ?? `Customer #${id}`
  }, [customers.data])

  const filtered = useMemo(() => {
    if (!customerId) return []
    const list = docs.data ?? []
    let result = list.filter((d) => d.customer_id === Number(customerId))
    const q = search.trim().toLowerCase()
    if (q) {
      result = result.filter((d) =>
        [d.original_filename, d.description, d.mime_type, customerName(d.customer_id)]
          .filter(Boolean)
          .some((v) => String(v).toLowerCase().includes(q))
      )
    }
    return result
  }, [docs.data, search, customerId, customerName])

  const uploadMutation = useMutation({
    mutationFn: (file: File) => documentApi.upload(Number(customerId), file, description || undefined),
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

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
      <Panel className="scroll-fade lg:col-span-1">
        <h2 className="mb-4 flex items-center gap-2 font-display text-sm font-bold tracking-wide text-navy-900 uppercase">
          <FolderUp size={15} className="text-brand-teal" /> Upload file
        </h2>
        <div className="flex flex-col gap-4">
          <Field label="Customer *">
            <select className={selectCls} value={customerId} onChange={(e) => setCustomerId(e.target.value)}>
              <option value="">— select —</option>
              {customers.data?.map((c) => (
                <option key={c.id} value={c.id}>{c.customer_name}</option>
              ))}
            </select>
          </Field>
          <Field label="Description">
            <input className={inputCls} value={description} onChange={(e) => setDescription(e.target.value)} />
          </Field>
          <input
            ref={fileRef}
            type="file"
            className="hidden"
            onChange={(e) => {
              setError(null)
              const f = e.target.files?.[0]
              if (f && customerId) uploadMutation.mutate(f)
              else if (f && !customerId) setError('Select a customer first')
            }}
          />
          <Button icon={<FolderUp size={15} />} disabled={uploadMutation.isPending} onClick={() => fileRef.current?.click()}>
            {uploadMutation.isPending ? 'Uploading…' : 'Choose file'}
          </Button>
          {error && <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-600">⚠ {error}</div>}
        </div>
      </Panel>

      <Panel className="scroll-fade lg:col-span-2" style={{ animationDelay: '0.1s' }}>
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="flex items-center gap-2 font-display text-sm font-bold tracking-wide text-navy-900 uppercase">
              <FileText size={15} className="text-brand-teal" /> Stored files
            </h2>
            <div className="mt-1 flex items-center gap-2">
              {customerId ? (
                <div className="flex items-center gap-2 rounded-xl border border-brand-teal/30 bg-brand-teal/10 px-3 py-1.5">
                  <span className="grid h-5 w-5 place-items-center rounded-full bg-gradient-to-br from-brand-teal to-brand-teal-dark text-[10px] font-bold text-white">
                    {customerName(Number(customerId)).charAt(0).toUpperCase()}
                  </span>
                  <span className="text-xs font-semibold text-brand-teal-dark">Viewing: {customerName(Number(customerId))}</span>
                  {!search && <Badge tone="teal">{filtered.length} file{filtered.length === 1 ? '' : 's'}</Badge>}
                </div>
              ) : (
                <span className="rounded-xl border border-slate-200 bg-slate-50/70 px-3 py-1.5 text-xs text-slate-400">
                  Select a customer to view their files
                </span>
              )}
            </div>
          </div>
          <div className="relative">
            <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input className={`${inputCls} w-56 pl-9`} value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search files…" />
          </div>
        </div>
        {docs.isLoading ? (
          <Spinner label="Loading files" />
        ) : (
          <div className="space-y-2">
            {filtered.map((d) => {
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
                        <span className="font-medium text-navy-700">{customerName(d.customer_id)}</span>
                        <span className="text-slate-300">·</span>
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
            {filtered.length === 0 && (
              <EmptyState message={
                !customerId
                  ? 'Select a customer to see their files'
                  : (search
                      ? 'No files match your search'
                      : `${customerName(Number(customerId))} has no stored files`)
              } />
            )}
          </div>
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
