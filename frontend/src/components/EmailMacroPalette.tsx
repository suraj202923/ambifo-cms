import { Braces } from 'lucide-react'

export const EMAIL_MACROS = [
  'customer_name',
  'account_name',
  'email',
  'phone',
  'city',
  'segment',
  'deal_status',
  'today',
  'meeting_availability_form_link',
  'meeting_availability_expires_at',
  'selected_diagrams_html',
  'your_diagram_macro',
]

export function EmailMacroPalette({ onInsert }: { onInsert: (macro: string) => void }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50/70 p-3">
      <div className="mb-2 flex items-center gap-1.5 font-display text-[11px] font-bold tracking-widest text-slate-500 uppercase">
        <Braces size={12} className="text-brand-teal" />
        {EMAIL_MACROS.length} macros available
      </div>
      <div className="flex flex-wrap gap-1.5">
        {EMAIL_MACROS.map((m) => (
          <button
            key={m}
            type="button"
            className="rounded-lg border border-slate-200 bg-white px-2 py-1 font-mono text-[11px] text-brand-teal-dark transition-colors hover:border-brand-teal hover:bg-brand-teal/10"
            title={`Insert {{${m}}}`}
            onClick={() => onInsert(`{{${m}}}`)}
          >
            {`{{${m}}}`}
          </button>
        ))}
      </div>
    </div>
  )
}
