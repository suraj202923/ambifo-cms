import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Calculator, Cloud, Edit3, ExternalLink, Eye, GitBranch, Trash2 } from 'lucide-react'
import { customerApi, diagramApi, documentApi } from '../api'
import type { Diagram } from '../api/types'
import { Badge, Button, EmptyState, Field, inputCls, PageHead, Panel, selectCls, Spinner } from '../components/ui'
import { DrawioEditorModal } from '../components/DrawioEditorModal'
import { buildStarterXml } from '../lib/drawio'

function formatRelative(iso: string): string {
  const d = new Date(iso)
  const diff = Date.now() - d.getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return d.toLocaleDateString()
}

function xmlToLightboxUrl(xml: string): string {
  const enc = btoa(unescape(encodeURIComponent(xml)))
  return `https://view.diagrams.net/?lightbox=1&highlight=0000ff&edit=_blank&layers=1&nav=1#R${enc}`
}

function dataUrlToBlob(dataUrl: string): Blob {
  const [meta, b64] = dataUrl.split(',')
  const mime = meta?.match(/data:(.*?);base64/)?.[1] ?? 'image/png'
  const bin = atob(b64 ?? '')
  const bytes = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i)
  return new Blob([bytes], { type: mime })
}

type EditorState = { mode: 'create' } | { mode: 'edit'; diagram: Diagram }

export default function DiagramsPage() {
  const queryClient = useQueryClient()
  const customers = useQuery({ queryKey: ['customers'], queryFn: () => customerApi.list({ limit: 200 }) })
  const diagrams = useQuery({ queryKey: ['diagrams'], queryFn: () => diagramApi.list() })

  const [form, setForm] = useState({ customer_id: '', diagram_name: '', aws_calculator_link: '' })
  const [error, setError] = useState<string | null>(null)
  const [docNote, setDocNote] = useState<string | null>(null)
  const [editor, setEditor] = useState<EditorState | null>(null)

  const customerName = useMemo(() => {
    const map = new Map<number, string>()
    customers.data?.forEach((c) => map.set(c.id, c.customer_name))
    return (id: number) => map.get(id) ?? `Customer #${id}`
  }, [customers.data])

  function onCustomerChange(cid: string) {
    const link = customers.data?.find((c) => String(c.id) === cid)?.aws_calculator_link ?? ''
    setForm((f) => ({ ...f, customer_id: cid, aws_calculator_link: link }))
  }

  const starterXml = useMemo(
    () => (editor?.mode === 'create' ? buildStarterXml(customerName(Number(form.customer_id)) || 'Client', form.aws_calculator_link?.trim() ?? '') : null),
    [editor, form.customer_id, form.aws_calculator_link, customerName],
  )

  const visibleDiagrams = useMemo(
    () => (form.customer_id ? (diagrams.data ?? []).filter((d) => d.customer_id === Number(form.customer_id)) : []),
    [diagrams.data, form.customer_id],
  )

  const createMutation = useMutation({
    mutationFn: (xml: string) =>
      diagramApi.save({
        customer_id: Number(form.customer_id),
        diagram_name: form.diagram_name || 'AWS Architecture',
        diagram_content: xml,
        aws_calculator_link: form.aws_calculator_link.trim() || null,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['diagrams'] })
      setEditor(null)
      setForm({ customer_id: '', diagram_name: '', aws_calculator_link: '' })
    },
    onError: (e) => setError(e instanceof Error ? e.message : 'Save failed'),
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, xml }: { id: number; xml: string }) => diagramApi.update(id, { diagram_content: xml }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['diagrams'] })
      setEditor(null)
    },
    onError: (e) => setError(e instanceof Error ? e.message : 'Save failed'),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => diagramApi.remove(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['diagrams'] }),
  })

  const docUploadMutation = useMutation({
    mutationFn: ({ customerId, file }: { customerId: number; file: File }) =>
      documentApi.upload(customerId, file, 'Architecture diagram (draw.io)'),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents'] })
      setDocNote('Diagram attached to the customer\'s documents.')
    },
    onError: (e) => setDocNote(e instanceof Error ? `Document upload failed: ${e.message}` : 'Document upload failed'),
  })

  function handleExportDocument(xml: string, pngDataUrl: string) {
    if (!editor) return
    setError(null)
    setDocNote(null)
    const customerId = editor.mode === 'edit' ? editor.diagram.customer_id : Number(form.customer_id)
    if (!customerId) {
      setError('Select a customer first')
      return
    }
    if (editor.mode === 'create') {
      createMutation.mutate(xml)
    } else {
      updateMutation.mutate({ id: editor.diagram.id, xml })
    }
    const nameBase = editor.mode === 'edit' ? editor.diagram.diagram_name : form.diagram_name || 'AWS Architecture'
    const safeName = nameBase.replace(/[/\\?%*:|"<>]/g, '_').replace(/\s+/g, '_')
    try {
      const file = new File([dataUrlToBlob(pngDataUrl)], `${safeName}.png`, { type: 'image/png' })
      docUploadMutation.mutate({ customerId, file })
    } catch {
      setDocNote('Could not read exported image — diagram saved, document not attached.')
    }
  }

  function openEditor() {
    setError(null)
    if (!form.customer_id) {
      setError('Select a customer first')
      return
    }
    setEditor({ mode: 'create' })
  }

  function handleEditorSave(xml: string) {
    if (editor?.mode === 'create') {
      if (!form.customer_id) return
      createMutation.mutate(xml)
    } else if (editor && editor.mode === 'edit') {
      updateMutation.mutate({ id: editor.diagram.id, xml })
    }
  }

  return (
    <div>
      <PageHead title="Diagrams" subtitle="Design AWS cloud architecture visually with the free draw.io editor" />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Panel className="scroll-fade h-fit lg:col-span-1">
          <h2 className="mb-4 flex items-center gap-2 font-display text-sm font-bold tracking-wide text-navy-900 uppercase">
            <Cloud size={15} className="text-brand-teal" /> New diagram
          </h2>
          <div className="flex flex-col gap-4">
            <Field label="Customer *">
              <select className={selectCls} value={form.customer_id} onChange={(e) => onCustomerChange(e.target.value)}>
                <option value="">— select —</option>
                {customers.data?.map((c) => (
                  <option key={c.id} value={c.id}>{c.customer_name}</option>
                ))}
              </select>
            </Field>
            <Field label="Diagram name">
              <input className={inputCls} value={form.diagram_name} onChange={(e) => setForm((f) => ({ ...f, diagram_name: e.target.value }))} placeholder="AWS Architecture" />
            </Field>
            <Field label="AWS calculator link">
              <div className="flex items-center gap-2">
                <input className={inputCls} value={form.aws_calculator_link} onChange={(e) => setForm((f) => ({ ...f, aws_calculator_link: e.target.value }))} placeholder="https://calculator.aws/…" />
                {form.aws_calculator_link.trim() ? (
                  <a className="shrink-0 rounded-lg border border-brand-teal/30 bg-brand-teal/10 p-2 text-brand-teal-dark transition-colors hover:bg-brand-teal/20" title="Open calculator" href={form.aws_calculator_link.trim()} target="_blank" rel="noopener noreferrer">
                    <ExternalLink size={15} />
                  </a>
                ) : (
                  <a className="shrink-0 rounded-lg border border-slate-200 p-2 text-slate-400 transition-colors hover:bg-slate-100 hover:text-navy-900" title="Open AWS Pricing Calculator" href="https://calculator.aws" target="_blank" rel="noopener noreferrer">
                    <Calculator size={15} />
                  </a>
                )}
              </div>
            </Field>
            <Button icon={<GitBranch size={15} />} onClick={openEditor}>
              Open draw.io editor
            </Button>
            <p className="text-xs text-slate-400">
              A starter architecture flow is pre-loaded in the draw.io editor — drag AWS services from the left shape library onto the canvas. <b>Save &amp; close</b> stores the diagram here; <b>Save + attach to docs</b> also embeds an image of it in the customer's Documents.
            </p>
            {error && <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-600">⚠ {error}</div>}
            {docNote && (
              <div className={`rounded-xl border px-4 py-3 text-sm ${docNote.startsWith('Document upload failed') ? 'border-red-200 bg-red-50 text-red-600' : 'border-emerald-200 bg-emerald-50 text-emerald-700'}`}>
                {docNote.startsWith('Document upload failed') ? `⚠ ${docNote}` : `✓ ${docNote}`}
              </div>
            )}
          </div>
        </Panel>

        <Panel className="scroll-fade lg:col-span-2" style={{ animationDelay: '0.1s' }}>
          <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
            <h2 className="flex items-center gap-2 font-display text-sm font-bold tracking-wide text-navy-900 uppercase">
              <GitBranch size={15} className="text-brand-teal" /> Saved diagrams
            </h2>
            {form.customer_id ? (
              <Badge tone="teal">{customerName(Number(form.customer_id))} — {visibleDiagrams.length} diagram{visibleDiagrams.length === 1 ? '' : 's'}</Badge>
            ) : (
              <Badge tone="neutral">Select a customer to view diagrams</Badge>
            )}
          </div>
          {diagrams.isLoading ? (
            <Spinner label="Loading diagrams" />
          ) : visibleDiagrams.length === 0 ? (
            <EmptyState message={form.customer_id ? 'No diagrams for this customer yet — create one above' : 'Select a customer above to see their diagrams'} />
          ) : (
            <div className="space-y-4">
              {visibleDiagrams.map((d) => (
                <div key={d.id} className="brand-card overflow-hidden rounded-2xl border border-slate-200">
                  <div className="flex items-center justify-between gap-3 border-b border-slate-100 px-4 py-3">
                    <div className="flex min-w-0 items-center gap-3">
                      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-brand-cyan to-brand-teal text-white">
                        <GitBranch size={15} />
                      </span>
                      <div className="min-w-0">
                        <div className="truncate font-display text-sm font-bold text-navy-900">{d.diagram_name}</div>
                        <div className="text-xs text-slate-400">
                          {customerName(d.customer_id)} · {formatRelative(d.updated_at)}
                        </div>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <Badge tone="cyan">{d.macro_key}</Badge>
                      {d.aws_calculator_link && (
                        <a className="flex items-center gap-1.5 rounded-full border border-orange-300/60 bg-orange-50 px-2.5 py-1 text-xs font-bold text-orange-600 transition-colors hover:bg-orange-100" title="Open AWS calculator estimate" href={d.aws_calculator_link} target="_blank" rel="noopener noreferrer">
                          <ExternalLink size={12} /> AWS calculator
                        </a>
                      )}
                      <button className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-brand-teal/10 hover:text-brand-teal-dark" title="View" onClick={() => setEditor({ mode: 'edit', diagram: d })}>
                        <Eye size={14} />
                      </button>
                      <button className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-navy-900" title="Edit" onClick={() => setEditor({ mode: 'edit', diagram: d })}>
                        <Edit3 size={14} />
                      </button>
                      <button className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-red-50 hover:text-red-600" title="Delete" onClick={() => { if (confirm('Delete this diagram?')) deleteMutation.mutate(d.id) }}>
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </div>
                  <div className="overflow-x-auto bg-[#0b1023]/95 p-4">
                    {d.diagram_content && d.diagram_content.includes('<mxfile') ? (
                      <iframe
                        title={d.diagram_name}
                        src={xmlToLightboxUrl(d.diagram_content)}
                        className="h-96 w-full rounded-xl border border-white/10 bg-white"
                      />
                    ) : (
                      <pre className="overflow-x-auto font-mono text-xs text-cyan-200">{d.diagram_content}</pre>
                    )}
                  </div>
                  <div className="flex items-center justify-end gap-2 border-t border-slate-100 px-4 py-2.5">
                    <Button variant="outline" className="!px-3 !py-1.5 text-xs" icon={<Edit3 size={13} />} onClick={() => setEditor({ mode: 'edit', diagram: d })}>
                      Edit in draw.io
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Panel>
      </div>

      <DrawioEditorModal
        open={editor !== null}
        title={editor?.mode === 'edit' ? editor.diagram.diagram_name : form.diagram_name || 'AWS Architecture'}
        initialXml={editor?.mode === 'edit' ? editor.diagram.diagram_content : (starterXml ?? '')}
        saving={createMutation.isPending || updateMutation.isPending}
        exportingDocument={docUploadMutation.isPending}
        onExportDocument={handleExportDocument}
        onSave={handleEditorSave}
        onClose={() => setEditor(null)}
      />
    </div>
  )
}
