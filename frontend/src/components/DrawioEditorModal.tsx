import { useCallback, useEffect, useRef } from 'react'
import { FileImage, X, Save } from 'lucide-react'
import { Button } from './ui'

const EMPTY_AWS_XML = `<mxfile host="app.diagrams.net"><diagram id="aws-canvas" name="AWS Architecture"><mxGraphModel dx="900" dy="650" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="1169" pageHeight="826" math="0" shadow="0"><root><mxCell id="0"/><mxCell id="1" parent="0"/></root></mxGraphModel></diagram></mxfile>`

interface DrawioEditorModalProps {
  open: boolean
  title: string
  initialXml?: string
  saving?: boolean
  exportingDocument?: boolean
  onSave: (xml: string) => void
  onExportDocument?: (xml: string, pngDataUrl: string) => void
  onClose: () => void
}

export function DrawioEditorModal({ open, title, initialXml, saving, exportingDocument, onSave, onExportDocument, onClose }: DrawioEditorModalProps) {
  const iframeRef = useRef<HTMLIFrameElement>(null)
  const onSaveRef = useRef(onSave)
  const onCloseRef = useRef(onClose)
  const onExportDocumentRef = useRef(onExportDocument)
  const pendingCloseRef = useRef(false)
  const chainRef = useRef<null | 'xml' | 'png'>(null)
  const chainXmlRef = useRef('')
  onSaveRef.current = onSave
  onCloseRef.current = onClose
  onExportDocumentRef.current = onExportDocument

  const send = useCallback((payload: Record<string, unknown>) => {
    iframeRef.current?.contentWindow?.postMessage(JSON.stringify(payload), '*')
  }, [])

  const requestSave = useCallback(
    (closeAfter: boolean) => {
      pendingCloseRef.current = closeAfter
      send({ action: 'export', format: 'xml' })
    },
    [send],
  )

  useEffect(() => {
    if (!open) return
    pendingCloseRef.current = false
    chainRef.current = null
    chainXmlRef.current = ''

    function handler(evt: MessageEvent) {
      const iframe = iframeRef.current
      if (!iframe || evt.source !== iframe.contentWindow) return
      let msg: Record<string, unknown>
      try {
        msg = typeof evt.data === 'string' ? JSON.parse(evt.data) : evt.data
      } catch {
        return
      }
      if (!msg || typeof msg !== 'object') return

      if (msg.event === 'init') {
        send({ action: 'load', xml: initialXml && initialXml.trim() ? initialXml : EMPTY_AWS_XML })
      } else if (msg.event === 'export' && msg.format === 'xml') {
        const xml = typeof msg.xml === 'string' ? msg.xml : ''
        if (chainRef.current === 'xml') {
          chainRef.current = 'png'
          chainXmlRef.current = xml
          send({ action: 'export', format: 'png' })
          return
        }
        onSaveRef.current(xml)
        if (pendingCloseRef.current) {
          pendingCloseRef.current = false
          onCloseRef.current()
        }
      } else if (msg.event === 'export' && msg.format === 'png') {
        if (chainRef.current === 'png') {
          chainRef.current = null
          const data = typeof msg.data === 'string' ? msg.data : ''
          const dataUrl = data.startsWith('data:') ? data : `data:image/png;base64,${data}`
          onExportDocumentRef.current?.(chainXmlRef.current, dataUrl)
        }
      } else if (msg.event === 'exit') {
        onCloseRef.current()
      }
    }

    window.addEventListener('message', handler)
    return () => window.removeEventListener('message', handler)
  }, [open, initialXml, send])

  if (!open) return null

  // noSaveBtn=1 -> single "Save and Exit" style button is replaced; we fully control save via the
  // export (xml) action, so hide the native buttons to avoid user confusion.
  const src = `https://embed.diagrams.net/?embed=1&ui=atlas&spin=1&modified=unsavedChanges&proto=json&libraries=1&noExitBtn=1`

  return (
    <div className="fixed inset-0 z-[60] flex flex-col bg-navy-950/90 p-2 backdrop-blur-sm sm:p-4">
      <div className="flex items-center justify-between gap-3 border-b border-white/10 pb-3">
        <div className="flex items-center gap-2">
          <span className="grid h-7 w-7 place-items-center rounded-lg bg-gradient-to-br from-brand-cyan to-brand-teal text-white">
            <Save size={15} />
          </span>
          <div>
            <div className="font-display text-sm font-bold text-white">{title || 'AWS Architecture'}</div>
            <div className="text-[11px] text-slate-400">draw.io editor · add AWS shapes from the left panel</div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            className="!border-white/15 !text-slate-200 hover:!bg-white/10"
            icon={<X size={14} />}
            onClick={() => onClose()}
          >
            Cancel
          </Button>
          <Button disabled={saving || exportingDocument} variant="outline" className="!border-emerald-400/50 !text-emerald-300 hover:!bg-emerald-400/10" icon={<FileImage size={14} />} onClick={() => { chainRef.current = 'xml'; send({ action: 'export', format: 'xml' }) }}>
            {exportingDocument ? 'Attaching…' : 'Save + attach to docs'}
          </Button>
          <Button disabled={saving} variant="outline" className="!border-brand-teal/50 !text-brand-cyan hover:!bg-brand-teal/10" icon={<Save size={14} />} onClick={() => requestSave(false)}>
            {saving ? 'Saving…' : 'Save'}
          </Button>
          <Button disabled={saving} icon={<Save size={14} />} onClick={() => requestSave(true)}>
            {saving ? 'Saving…' : 'Save & close'}
          </Button>
        </div>
      </div>
      <iframe ref={iframeRef} title="draw.io editor" src={src} className="mt-3 flex-1 rounded-xl border border-white/10 bg-white" allowFullScreen />
    </div>
  )
}
