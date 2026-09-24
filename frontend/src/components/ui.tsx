import type { ReactNode } from 'react'
import { Loader2, X } from 'lucide-react'

export function FilePreviewModal({
  filename,
  content,
  blobUrl,
  loading,
  error,
  onClose,
}: {
  filename: string
  content?: string | null
  blobUrl?: string | null
  loading?: boolean
  error?: string | null
  onClose: () => void
}) {
  if (!content && !blobUrl) return null
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-navy-900/60 backdrop-blur-sm" onClick={onClose} />
      <div className="relative flex max-h-[85vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl">
        <div className="flex items-center justify-between gap-4 border-b border-slate-200 px-5 py-3">
          <div className="min-w-0 truncate font-display text-sm font-bold text-navy-900">{filename}</div>
          <div className="flex items-center gap-2">
            {blobUrl && !content && (
              <a
                className="rounded-lg px-3 py-1.5 text-xs font-semibold text-brand-teal-dark transition-colors hover:bg-brand-teal/10"
                href={blobUrl}
                target="_blank"
                rel="noopener noreferrer"
              >
                Open in new tab ↗
              </a>
            )}
            <button
              className="rounded-lg p-2 text-slate-400 transition-colors hover:bg-slate-100 hover:text-navy-900"
              onClick={onClose}
              title="Close"
            >
              <X size={17} />
            </button>
          </div>
        </div>
        <div className="flex-1 overflow-auto bg-slate-50 p-4">
          {loading ? (
            <div className="flex items-center justify-center gap-2 py-12 text-slate-400">
              <Loader2 size={18} className="animate-spin text-brand-teal" />
              <span className="text-sm">Loading preview…</span>
            </div>
          ) : error ? (
            <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-600">⚠ {error}</div>
          ) : content != null ? (
            <pre className="max-h-[70vh] overflow-auto whitespace-pre-wrap break-words rounded-xl border border-slate-200 bg-white p-4 text-xs leading-relaxed text-slate-700">
              {content}
            </pre>
          ) : blobUrl ? (
            <iframe
              className="h-[70vh] w-full rounded-xl border border-slate-200 bg-white"
              src={blobUrl}
              title={filename}
            />
          ) : (
            <EmptyState message="No preview available" />
          )}
        </div>
      </div>
    </div>
  )
}

export function isTextPreview(filename: string, mimeType?: string | null): boolean {
  if (mimeType?.startsWith('text/')) return true
  const ext = (filename.split('.').pop() || '').toLowerCase()
  return [
    'csv',
    'txt',
    'md',
    'json',
    'xml',
    'html',
    'log',
    'yml',
    'yaml',
    'ini',
    'env',
    'ts',
    'js',
    'py',
  ].includes(ext)
}

export function Badge({
  children,
  tone = 'neutral',
}: {
  children: ReactNode
  tone?: 'neutral' | 'teal' | 'cyan' | 'green' | 'coral' | 'navy'
}) {
  const tones: Record<string, string> = {
    neutral: 'bg-slate-100 text-slate-700 border-slate-200',
    teal: 'bg-brand-teal/12 text-brand-teal-dark border-brand-teal/25',
    cyan: 'bg-brand-cyan/12 text-cyan-700 border-brand-cyan/25',
    green: 'bg-green-100 text-green-700 border-green-200',
    coral: 'bg-red-50 text-red-600 border-red-200',
    navy: 'bg-navy-900/8 text-navy-800 border-navy-900/10',
  }
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-semibold ${tones[tone]}`}
    >
      {children}
    </span>
  )
}

export function PageHead({
  title,
  subtitle,
  actions,
}: {
  title: string
  subtitle?: ReactNode
  actions?: ReactNode
}) {
  return (
    <div className="scroll-fade mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="font-display text-3xl font-bold text-navy-900">{title}</h1>
        {subtitle && <div className="mt-1 text-sm text-slate-500">{subtitle}</div>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  )
}

export function Panel({
  children,
  className = '',
  ...rest
}: { children: ReactNode; className?: string; style?: React.CSSProperties }) {
  return (
    <section
      {...rest}
      className={`brand-card rounded-2xl border border-slate-200 bg-white p-6 shadow-sm ${className}`}
    >
      {children}
    </section>
  )
}

export function PanelTitle({ children }: { children: ReactNode }) {
  return (
    <h2 className="mb-4 flex items-center gap-2 font-display text-sm font-bold tracking-wide text-navy-900 uppercase">
      {children}
    </h2>
  )
}

export function Button({
  children,
  variant = 'primary',
  icon,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'ghost' | 'outline'
  icon?: ReactNode
}) {
  const variants: Record<string, string> = {
    primary:
      'bg-gradient-to-r from-brand-teal to-brand-teal-dark text-white shadow-lg shadow-brand-teal/25 hover:shadow-brand-teal/40 hover:-translate-y-0.5',
    secondary:
      'bg-gradient-to-r from-brand-cyan to-brand-teal text-navy-900 shadow-lg shadow-brand-cyan/20 hover:-translate-y-0.5',
    outline:
      'border-2 border-brand-teal text-brand-teal-dark hover:bg-brand-teal hover:text-white',
    ghost: 'border border-slate-200 text-slate-600 hover:bg-slate-100',
  }
  return (
    <button
      {...props}
      className={`inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2 font-display text-sm font-bold transition-all duration-300 disabled:opacity-50 disabled:pointer-events-none ${
        variants[variant]
      } ${props.className ?? ''}`}
    >
      {icon}
      {children}
    </button>
  )
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-10 text-slate-500">
      <Loader2 size={20} className="animate-spin text-brand-teal" />
      <span className="font-display text-sm font-semibold">{label ?? 'Loading…'}</span>
    </div>
  )
}

export function Field({
  label,
  className = '',
  children,
}: {
  label: ReactNode
  className?: string
  children: ReactNode
}) {
  return (
    <label className={`block ${className}`}>
      <span className="mb-1.5 block font-display text-xs font-bold tracking-wide text-slate-600 uppercase">
        {label}
      </span>
      {children}
    </label>
  )
}

export const inputCls =
  'w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 shadow-sm outline-none transition-all duration-200 focus:border-brand-teal focus:ring-2 focus:ring-brand-teal/20'

export const selectCls = inputCls

export function EmptyState({ message }: { message: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-14 text-center text-slate-400">
      <span className="text-3xl">✦</span>
      <p className="font-display text-sm font-semibold">{message}</p>
    </div>
  )
}

export function PageLoading({ label }: { label?: string }) {
  return (
    <div className="flex min-h-[60vh] items-center justify-center">
      <div className="flex flex-col items-center gap-3">
        <div className="h-10 w-10 animate-spin rounded-full border-2 border-brand-teal/20 border-t-brand-teal" />
        <span className="font-display text-sm font-semibold text-slate-500">
          {label ?? 'Loading'}
        </span>
      </div>
    </div>
  )
}