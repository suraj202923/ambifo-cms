import { useEffect, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { CalendarClock, Check } from 'lucide-react'
import { publicMeetingApi } from '../api'
import type { MeetingAvailability } from '../api/types'
import PublicShell, { PublicError, PublicThanks } from '../components/PublicShell'
import { Button, Field, inputCls } from '../components/ui'

const fmt = (v: string) => new Date(v).toLocaleString()
const toISO = (local: string) => (local ? new Date(local).toISOString() : '')

function errorMessage(e: unknown): string {
  if (e instanceof Error) {
    if (e.message.includes('expired')) return 'This availability link has expired.'
    if (e.message.includes('responded') || e.message.includes('Already')) return 'This link has already been responded to.'
    return e.message
  }
  return 'Something went wrong.'
}

export default function PublicMeetingPage() {
  const { token = '', action = '' } = useParams()
  if (action === 'form') return <PublicMeetingForm token={token} key={token} />
  if (action === '1' || action === '2' || action === '3')
    return <PublicMeetingSelect token={token} option={Number(action) as 1 | 2 | 3} key={token} />
  return <PublicMeetingPicker token={token} key={token} />
}

function PublicMeetingPicker({ token }: { token: string }) {
  const info = useQuery({
    queryKey: ['pub-meeting', token],
    queryFn: () => publicMeetingApi.getAvailability(token),
    retry: false,
  })
  const [error, setError] = useState<string | null>(null)

  const select = useMutation({
    mutationFn: (option: 1 | 2 | 3) => publicMeetingApi.select(token, option),
    onError: (e) => setError(errorMessage(e)),
  })

  if (info.isLoading) return <PublicShell><div className="text-center text-slate-400">Loading…</div></PublicShell>
  if (info.error) return <PublicShell><PublicError message={errorMessage(info.error)} /></PublicShell>

  const a = info.data as MeetingAvailability
  const responded = a.status === 'selected' || a.status === 'submitted-form'
  const options = [a.option_1_at, a.option_2_at, a.option_3_at]

  return (
    <PublicShell>
      <div className="mb-6 flex items-center gap-2 text-brand-teal-dark">
        <CalendarClock size={18} /> Schedule your meeting
      </div>
      <div className="space-y-4">
        {responded ? (
          <PublicThanks title="You've already picked a time." message="Thanks — we'll follow up to confirm the meeting." />
        ) : (
          <>
            <div className="brand-card rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
              <p className="mb-4 text-sm text-slate-600">
                Pick the slot that works best for you — one click, done.
              </p>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                {options.map((o, idx) => (
                  <button
                    key={idx}
                    onClick={() => select.mutate((idx + 1) as 1 | 2 | 3)}
                    disabled={select.isPending}
                    className="group rounded-2xl border-2 border-slate-200 bg-white p-4 text-left transition-all duration-300 hover:-translate-y-0.5 hover:border-brand-teal hover:shadow-lg hover:shadow-brand-teal/15 disabled:opacity-50"
                  >
                    <div className="font-display text-xs font-bold tracking-widest text-slate-400 uppercase">
                      Option {idx + 1}
                    </div>
                    <div className="mt-1 font-display text-sm font-bold text-navy-900">{fmt(o)}</div>
                    <div className="mt-2 text-xs font-semibold text-brand-teal opacity-0 transition-opacity group-hover:opacity-100">
                      Select this →
                    </div>
                  </button>
                ))}
              </div>
              {select.isSuccess && (
                <div className="mt-4 rounded-xl bg-green-50 p-4 text-sm font-semibold text-green-700">
                  <Check size={15} className="mr-1 inline" /> You selected{' '}
                  {fmt(options[(select.variables as 1 | 2 | 3) - 1])}. Thanks!
                </div>
              )}
              {error && <p className="mt-4 text-xs font-semibold text-red-600">{error}</p>}
            </div>
            <p className="text-center text-sm text-slate-500">
              None of these work?{' '}
              <a href={`/public/meetings/${token}/form`} className="font-semibold text-brand-teal-dark hover:underline">
                Suggest your own times
              </a>
            </p>
          </>
        )}
      </div>
    </PublicShell>
  )
}

function PublicMeetingSelect({ token, option }: { token: string; option: 1 | 2 | 3 }) {
  const [result, setResult] = useState<MeetingAvailability | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    publicMeetingApi
      .select(token, option)
      .then(setResult)
      .catch((e) => setError(errorMessage(e)))
  }, [token, option])

  return (
    <PublicShell>
      {result ? (
        <PublicThanks
          title={`You picked option ${result.selected_option ?? option}: ${fmt([result.option_1_at, result.option_2_at, result.option_3_at][(result.selected_option ?? option) - 1])}`}
          message="Thanks — we'll follow up to confirm the meeting."
        />
      ) : error ? (
        <PublicError message={error} />
      ) : (
        <div className="text-center text-slate-400">Recording your selection…</div>
      )}
    </PublicShell>
  )
}

function PublicMeetingForm({ token }: { token: string }) {
  const info = useQuery({
    queryKey: ['pub-meeting-form', token],
    queryFn: () => publicMeetingApi.getAvailability(token),
    retry: false,
  })
  const [option_1_at, set1] = useState('')
  const [option_2_at, set2] = useState('')
  const [option_3_at, set3] = useState('')
  const [extra_recipients, setExtra] = useState('')
  const [customer_note, setNote] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState<MeetingAvailability | null>(null)

  const toLocal = (v: string) => new Date(v).toLocaleString('sv-SE').replace(' ', 'T').slice(0, 16)

  useEffect(() => {
    if (info.data) {
      set1(toLocal(info.data.option_1_at))
      set2(toLocal(info.data.option_2_at))
      set3(toLocal(info.data.option_3_at))
    }
  }, [info.data])

  function submit() {
    const slots = [option_1_at, option_2_at, option_3_at]
    if (slots.some((s) => !s)) {
      setError('Please fill in all three proposed times.')
      return
    }
    if (new Set(slots).size !== 3) {
      setError('The three times must be distinct.')
      return
    }
    publicMeetingApi
      .form(token, {
        option_1_at: toISO(option_1_at),
        option_2_at: toISO(option_2_at),
        option_3_at: toISO(option_3_at),
        extra_recipients: extra_recipients || null,
        customer_note: customer_note || null,
      })
      .then(setDone)
      .catch((e) => setError(errorMessage(e)))
  }

  if (info.isLoading) return <PublicShell><div className="text-center text-slate-400">Loading…</div></PublicShell>
  if (info.error) return <PublicShell><PublicError message={errorMessage(info.error)} /></PublicShell>
  if (done) {
    const slots = [done.customer_option_1_at, done.customer_option_2_at, done.customer_option_3_at].filter((x): x is string => Boolean(x))
    return (
      <PublicShell>
        <PublicThanks
          title="Your proposed times were sent."
          message={slots.length ? `We'll check ${slots.map((s) => fmt(s)).join(', ')} and confirm.` : undefined}
        />
      </PublicShell>
    )
  }

  return (
    <PublicShell>
      <h1 className="mb-1 font-display text-2xl font-bold text-navy-900">Suggest your own times</h1>
      <p className="mb-6 text-sm text-slate-500">Propose three times that work for you.</p>
      <div className="brand-card rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          {[
            ['1', option_1_at, set1],
            ['2', option_2_at, set2],
            ['3', option_3_at, set3],
          ].map(([n, val, set]) => (
            <Field key={String(n)} label={`Proposed time ${String(n)}`}>
              <input
                className={inputCls}
                type="datetime-local"
                value={val as string}
                onChange={(e) => (set as (s: string) => void)(e.target.value)}
              />
            </Field>
          ))}
        </div>
        <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Additional recipients (comma separated)">
            <input
              className={inputCls}
              type="email"
              multiple
              placeholder="a@corp.com, b@corp.com"
              value={extra_recipients}
              onChange={(e) => setExtra(e.target.value)}
            />
          </Field>
          <Field label="Note for Ambifo">
            <input
              className={inputCls}
              placeholder="Anything we should know?"
              value={customer_note}
              onChange={(e) => setNote(e.target.value)}
            />
          </Field>
        </div>
        {error && <p className="mt-4 text-xs font-semibold text-red-600">{error}</p>}
        <div className="mt-5">
          <Button onClick={submit}>Send my proposed times</Button>
        </div>
      </div>
    </PublicShell>
  )
}