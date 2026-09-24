import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Bot, Send, Sparkles } from 'lucide-react'
import { aiApi } from '../api'
import { Button, Field, inputCls, PageHead, Panel, selectCls, Spinner } from '../components/ui'

const PRESETS = [
  {
    label: 'Draft a demo follow-up email',
    prompt:
      'Write a friendly, professional follow-up email to a prospect after a cloud migration demo. Keep it under 120 words and include a clear next step.',
  },
  {
    label: 'Summarize a win as a case study',
    prompt:
      'Turn the following into a concise customer case study for our website: cloud infrastructure modernization reduced costs 30%, improved reliability, enabled hybrid cloud.',
  },
  {
    label: 'Generate a cloud architecture proposal',
    prompt:
      'Outline a 5-point cloud modernization proposal for a legacy data-center customer: discovery, architecture, migration, optimization, governance.',
  },
]

export default function AiPage() {
  const [provider, setProvider] = useState<'openai' | 'gemini'>('openai')
  const [apiKey, setApiKey] = useState('')
  const [model, setModel] = useState('')
  const [prompt, setPrompt] = useState('')
  const [output, setOutput] = useState('')

  const mutation = useMutation({
    mutationFn: () =>
      aiApi.generate({
        provider,
        prompt,
        api_key: apiKey,
        model: model || undefined,
      }),
    onSuccess: (res) => setOutput(res.content),
  })

  return (
    <div>
      <PageHead title="AI Assistant" subtitle="Orchestrated by the Rust engine — OpenAI or Gemini" />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Panel className="scroll-fade lg:col-span-1">
          <h2 className="mb-4 flex items-center gap-2 font-display text-sm font-bold tracking-wide text-navy-900 uppercase">
            <Sparkles size={15} className="text-brand-teal" /> Request
          </h2>
          <div className="flex flex-col gap-4">
            <Field label="Provider">
              <select className={selectCls} value={provider} onChange={(e) => setProvider(e.target.value as 'openai' | 'gemini')}>
                <option value="openai">OpenAI</option>
                <option value="gemini">Gemini</option>
              </select>
            </Field>
            <Field label="API key">
              <input type="password" className={inputCls} value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder="sk-… or AIza…" />
            </Field>
            <Field label="Model (optional)">
              <input className={inputCls} value={model} onChange={(e) => setModel(e.target.value)} placeholder={`default: ${provider === 'openai' ? 'gpt-4o-mini' : 'gemini-1.5-flash'}`} />
            </Field>

            <div>
              <div className="mb-1.5 font-display text-xs font-bold tracking-widest text-slate-600 uppercase">Presets</div>
              <div className="space-y-1">
                {PRESETS.map((p) => (
                  <button key={p.label} className="w-full rounded-lg border border-slate-200 px-3 py-2 text-left text-xs text-slate-600 transition-all duration-200 hover:border-brand-teal/40 hover:bg-brand-teal/5 hover:text-navy-900" onClick={() => setPrompt(p.prompt)}>
                    {p.label}
                  </button>
                ))}
              </div>
            </div>

            <Button
              variant="secondary"
              icon={<Bot size={15} />}
              disabled={mutation.isPending || !prompt.trim() || !apiKey.trim()}
              onClick={() => mutation.mutate()}
            >
              {mutation.isPending ? 'Generating…' : 'Generate'}
            </Button>
            <p className="text-[11px] text-slate-400">
              Your API key is sent only to the local engine and never stored.
            </p>
          </div>
        </Panel>

        <Panel className="scroll-fade lg:col-span-2" style={{ animationDelay: '0.1s' }}>
          <h2 className="mb-4 flex items-center gap-2 font-display text-sm font-bold tracking-wide text-navy-900 uppercase">
            <Send size={15} className="text-brand-teal" /> Result
          </h2>
          {mutation.isPending ? (
            <Spinner label="Engine is contacting the model" />
          ) : output ? (
            <div className="flex flex-col gap-4">
              <div className="rounded-xl border border-brand-teal/20 bg-slate-50 p-5 whitespace-pre-wrap text-sm text-slate-700 animate-fade-in">
                {output}
              </div>
              <Button variant="ghost" onClick={() => setOutput('')}>Clear</Button>
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center gap-3 py-16 text-slate-400">
              <span className="relative flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-brand-cyan to-brand-teal text-navy-900 shadow-lg shadow-brand-cyan/20">
                <Bot size={28} />
                <span className="absolute -right-0.5 -top-0.5 h-3 w-3 animate-pulse rounded-full bg-brand-green" />
              </span>
              <p className="font-display text-sm font-semibold">Ask the engine anything</p>
              <p className="max-w-sm text-center text-xs">Pick a preset or write your own prompt, add a provider API key, and hit Generate.</p>
            </div>
          )}
        </Panel>
      </div>
    </div>
  )
}