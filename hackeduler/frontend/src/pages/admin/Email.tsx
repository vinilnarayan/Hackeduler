import { useEffect, useState } from 'react'
import { RotateCcw } from 'lucide-react'
import { get, post, put, qs, validationMessage } from '../../api/client'
import { Empty, ErrorState, Field, Modal, PageHeader, Pill, Spinner } from '../../components/ui'
import { fmtDateTime } from '../../lib/dates'
import { useToast } from '../../lib/toast'
import { useAsync } from '../../lib/useAsync'
import { SortTh, useSort } from '../../components/SortTh'
import RichEmailEditor from '../../components/RichEmailEditor'
import { COLOURS, LAYOUTS, isHex, textToHtml } from '../../lib/emailDesign'

export default function EmailPage() {
  const [tab, setTab] = useState<'templates' | 'logs'>('templates')
  return (
    <div>
      <PageHeader title="Email & Templates" subtitle="Notifications are queued in a transactional outbox and delivered by the background worker with retries. Sender and recipients are configured under Settings; SMTP credentials live only in server environment variables." />
      <div className="mb-3 flex gap-1">{(['templates', 'logs'] as const).map((t) => <button key={t} className={tab === t ? 'btn-primary' : 'btn-secondary'} onClick={() => setTab(t)}>{t === 'templates' ? 'Templates' : 'Delivery log'}</button>)}</div>
      {tab === 'templates' ? <Templates /> : <Logs />}
    </div>
  )
}

function Templates() {
  const toast = useToast()
  const { data, error, loading, reload } = useAsync<any[]>(() => get('/api/admin/email-templates'))
  const vars = useAsync<string[]>(() => get('/api/admin/email-templates/variables'))
  const [edit, setEdit] = useState<any>(null)
  const [preview, setPreview] = useState<any>(null)
  const [device, setDevice] = useState<'desktop' | 'phone'>('desktop')
  const [converted, setConverted] = useState(false)

  // Live preview: re-render (on the server, so it is exactly what is sent) shortly after each change.
  useEffect(() => {
    if (!edit) { setPreview(null); return }
    let live = true
    const t = setTimeout(async () => {
      try { const r = await post(`/api/admin/email-templates/${edit.key}/preview`, { subject_template: edit.subject_template, body_template: edit.body_template, body_format: 'html', layout: edit.layout, accent: edit.accent }); if (live) setPreview(r) }
      catch (e) { if (live) setPreview({ error: validationMessage(e) }) }
    }, 400)
    return () => { live = false; clearTimeout(t) }
  }, [edit?.key, edit?.subject_template, edit?.body_template, edit?.layout, edit?.accent]) // eslint-disable-line react-hooks/exhaustive-deps

  const open = (t: any) => {
    const wasText = t.body_format !== 'html'
    setConverted(wasText)
    setDevice('desktop')
    setEdit({ ...t, body_format: 'html', body_template: wasText ? textToHtml(t.body_template) : t.body_template })
  }
  const save = async () => {
    try {
      await put(`/api/admin/email-templates/${edit.key}`, { subject_template: edit.subject_template, body_template: edit.body_template, body_format: 'html', layout: edit.layout, accent: edit.accent, is_active: edit.is_active })
      toast('success', 'Template saved'); setEdit(null); reload()
    } catch (e) { toast('error', validationMessage(e)) }
  }

  if (error) return <ErrorState message={error} onRetry={reload} />
  if (loading) return <Spinner />
  return (
    <>
      <div className="card divide-y divide-slate-100">{data!.map((t) => (
        <div key={t.key} className="flex flex-wrap items-center gap-3 px-4 py-3">
          <div className="min-w-0 flex-1"><div className="font-medium">{t.name} {!t.is_active && <Pill>Disabled</Pill>}</div><div className="truncate font-mono text-xs text-slate-500">{t.subject_template}</div></div>
          <button className="btn-secondary" onClick={() => open(t)}>Edit</button>
        </div>
      ))}</div>
      <Modal open={!!edit} onClose={() => setEdit(null)} size="xl" title={`Template: ${edit?.name}`}
        footer={<><button className="btn-secondary" onClick={() => setEdit(null)}>Cancel</button><button className="btn-primary" onClick={save}>Save</button></>}>
        {edit && <div className="grid gap-4 lg:grid-cols-2">
          <div className="min-w-0 space-y-3">
            {converted && <div className="rounded border border-blue-200 bg-blue-50 px-3 py-2 text-xs text-blue-900">This template was written in the older text style. It has been converted for the visual editor; nothing changes until you click Save.</div>}
            <Field label="Subject" htmlFor="t-s"><input id="t-s" className="input font-mono text-xs" value={edit.subject_template} onChange={(e) => setEdit({ ...edit, subject_template: e.target.value })} /></Field>
            <div><div className="label">Body</div>
              <RichEmailEditor value={edit.body_template} resetKey={edit.key} variables={vars.data ?? []} onChange={(html) => setEdit((p: any) => ({ ...p, body_template: html }))} /></div>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={edit.is_active} onChange={(e) => setEdit({ ...edit, is_active: e.target.checked })} />Template enabled</label>
          </div>
          <div className="min-w-0 space-y-3">
            <div>
              <div className="label">Design</div>
              <div className="flex flex-wrap gap-1" role="group" aria-label="Design">{LAYOUTS.map((l) => (
                <button key={l.id} type="button" title={l.hint} aria-pressed={edit.layout === l.id} className={edit.layout === l.id ? 'btn-primary' : 'btn-secondary'} onClick={() => setEdit({ ...edit, layout: l.id })}>{l.label}</button>
              ))}</div>
            </div>
            <div>
              <div className="label">Colour</div>
              <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Colour">
                {COLOURS.map((c) => (
                  <button key={c.hex} type="button" aria-label={c.name} aria-pressed={edit.accent.toLowerCase() === c.hex} title={c.name} onClick={() => setEdit({ ...edit, accent: c.hex })}
                    className={`h-7 w-7 rounded-full border-2 border-white ring-1 ring-slate-300 ${edit.accent.toLowerCase() === c.hex ? 'ring-2 ring-slate-900' : ''}`} style={{ background: c.hex }} />
                ))}
                <label className="ml-1 flex items-center gap-1 text-xs text-slate-600">Custom
                  <input type="color" aria-label="Custom colour" className="h-7 w-9 cursor-pointer rounded border border-slate-300 bg-white p-0.5" value={isHex(edit.accent) ? edit.accent : '#0f2744'} onChange={(e) => setEdit({ ...edit, accent: e.target.value })} />
                </label>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="label mb-0">Preview as</span>
              <div className="flex gap-1" role="group" aria-label="Device">{(['desktop', 'phone'] as const).map((d) => <button key={d} type="button" aria-pressed={device === d} className={device === d ? 'btn-primary' : 'btn-secondary'} onClick={() => setDevice(d)}>{d === 'desktop' ? 'Desktop' : 'Phone'}</button>)}</div>
            </div>
            <div className="rounded border border-slate-200 bg-slate-50 p-3 text-xs" data-testid="email-preview">
              {!preview ? <div className="text-slate-500">Preparing preview...</div> : preview.error ? <div className="text-red-700">{preview.error}</div> : (
                <>
                  <div className="mb-2 font-semibold">Subject: {preview.subject}</div>
                  <div className="flex justify-center overflow-x-auto rounded bg-slate-200 p-2">
                    <iframe title="Email preview" sandbox="" srcDoc={preview.html} style={{ width: device === 'phone' ? 360 : '100%', maxWidth: '100%' }} className="h-[32rem] rounded border border-slate-300 bg-white" />
                  </div>
                  <details className="mt-2"><summary className="cursor-pointer text-slate-600">Plain-text version (for email clients that do not show HTML)</summary><pre className="mt-1 whitespace-pre-wrap font-sans">{preview.body}</pre></details>
                  <p className="mt-2 text-slate-500">Variables show as &lt;Name&gt; here and are replaced with real values when the email is sent.</p>
                </>
              )}
            </div>
          </div>
        </div>}
      </Modal>
    </>
  )
}

function Logs() {
  const toast = useToast()
  const [status, setStatus] = useState('')
  const [recipient, setRecipient] = useState('')
  const { data, error, loading, reload } = useAsync<any[]>(() => get('/api/admin/email-logs' + qs({ status, recipient })), [status, recipient])
  const tbl = useSort(data, { created: (e) => e.created_at, template: (e) => e.template_key, recipient: (e) => e.recipient, subject: (e) => e.subject, status: (e) => e.status, attempts: (e) => e.attempts, via: (e) => e.provider, error: (e) => e.last_error })
  const tone: Record<string, string> = { sent: 'bg-emerald-100 text-emerald-800', queued: 'bg-blue-100 text-blue-800', failed: 'bg-red-100 text-red-800' }
  return (
    <>
      <div className="mb-3 flex flex-wrap gap-2">
        <select className="input w-40" aria-label="Delivery status" value={status} onChange={(e) => setStatus(e.target.value)}><option value="">All statuses</option><option value="queued">Queued</option><option value="sent">Sent</option><option value="failed">Failed</option></select>
        <input className="input w-64" placeholder="Recipient" aria-label="Recipient" value={recipient} onChange={(e) => setRecipient(e.target.value)} />
        <button className="btn-secondary" onClick={reload}>Refresh</button>
      </div>
      <div className="card overflow-x-auto">
        {error ? <ErrorState message={error} onRetry={reload} /> : loading ? <Spinner /> : !data?.length ? <Empty title="No emails" /> : (
          <table className="min-w-full divide-y divide-slate-200">
            <thead className="bg-slate-50"><tr><SortTh label="Created" k="created" sort={tbl.sort} onToggle={tbl.toggle} /><SortTh label="Template" k="template" sort={tbl.sort} onToggle={tbl.toggle} /><SortTh label="Recipient" k="recipient" sort={tbl.sort} onToggle={tbl.toggle} /><SortTh label="Subject" k="subject" sort={tbl.sort} onToggle={tbl.toggle} /><SortTh label="Status" k="status" sort={tbl.sort} onToggle={tbl.toggle} /><SortTh label="Attempts" k="attempts" sort={tbl.sort} onToggle={tbl.toggle} /><SortTh label="Sent via" k="via" sort={tbl.sort} onToggle={tbl.toggle} /><SortTh label="Error" k="error" sort={tbl.sort} onToggle={tbl.toggle} /><th className="th" /></tr></thead>
            <tbody className="divide-y divide-slate-100">{tbl.sorted.map((e) => (
              <tr key={e.id}><td className="td text-xs whitespace-nowrap">{fmtDateTime(e.created_at)}</td><td className="td text-xs">{e.template_key}</td><td className="td text-xs">{e.recipient}</td><td className="td max-w-xs truncate text-xs">{e.subject}</td>
                <td className="td"><Pill className={tone[e.status]}>{e.status}</Pill>{e.sent_at && <div className="text-[11px] text-slate-500">{fmtDateTime(e.sent_at)}</div>}</td>
                <td className="td text-xs">{e.attempts}/{e.max_attempts}{e.status === 'queued' && e.attempts > 0 && <div className="text-slate-500">next {fmtDateTime(e.next_attempt_at)}</div>}</td>
                <td className="td text-xs uppercase">{e.provider ?? ''}</td>
                <td className="td max-w-xs text-xs text-red-700">{e.last_error}</td>
                <td className="td">{e.status !== 'sent' && <button className="btn-ghost px-2" aria-label="Retry delivery" onClick={async () => { try { await post(`/api/admin/email-logs/${e.id}/retry`); toast('success', 'Requeued'); reload() } catch (err) { toast('error', validationMessage(err)) } }}><RotateCcw className="h-4 w-4" /></button>}</td></tr>
            ))}</tbody>
          </table>
        )}
      </div>
    </>
  )
}
