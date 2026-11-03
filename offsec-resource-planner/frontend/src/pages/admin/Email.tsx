import { useState } from 'react'
import { RotateCcw } from 'lucide-react'
import { get, post, put, qs, validationMessage } from '../../api/client'
import { Empty, ErrorState, Field, Modal, PageHeader, Pill, Spinner } from '../../components/ui'
import { fmtDateTime } from '../../lib/dates'
import { useToast } from '../../lib/toast'
import { useAsync } from '../../lib/useAsync'

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
  if (error) return <ErrorState message={error} onRetry={reload} />
  if (loading) return <Spinner />
  return (
    <>
      <div className="card divide-y divide-slate-100">{data!.map((t) => (
        <div key={t.key} className="flex flex-wrap items-center gap-3 px-4 py-3">
          <div className="min-w-0 flex-1"><div className="font-medium">{t.name} {!t.is_active && <Pill>Disabled</Pill>}</div><div className="truncate font-mono text-xs text-slate-500">{t.subject_template}</div></div>
          <button className="btn-secondary" onClick={() => { setEdit({ ...t }); setPreview(null) }}>Edit</button>
        </div>
      ))}</div>
      <Modal open={!!edit} onClose={() => setEdit(null)} size="lg" title={`Template: ${edit?.name}`}
        footer={<>
          <button className="btn-secondary" onClick={async () => { try { setPreview(await post(`/api/admin/email-templates/${edit.key}/preview`, { subject_template: edit.subject_template, body_template: edit.body_template })) } catch (e) { toast('error', validationMessage(e)) } }}>Preview</button>
          <button className="btn-primary" onClick={async () => { try { await put(`/api/admin/email-templates/${edit.key}`, { subject_template: edit.subject_template, body_template: edit.body_template, is_active: edit.is_active }); toast('success', 'Template saved'); setEdit(null); reload() } catch (e) { toast('error', validationMessage(e)) } }}>Save</button>
        </>}>
        {edit && <div className="space-y-3">
          <Field label="Subject" htmlFor="t-s"><input id="t-s" className="input font-mono text-xs" value={edit.subject_template} onChange={(e) => setEdit({ ...edit, subject_template: e.target.value })} /></Field>
          <Field label="Body (plain text)" htmlFor="t-b"><textarea id="t-b" className="input min-h-72 font-mono text-xs" value={edit.body_template} onChange={(e) => setEdit({ ...edit, body_template: e.target.value })} /></Field>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={edit.is_active} onChange={(e) => setEdit({ ...edit, is_active: e.target.checked })} />Template enabled</label>
          <div className="text-xs text-slate-600">Allowed variables (safe substitution, no code evaluation): {vars.data?.map((v) => <code key={v} className="mr-1 rounded bg-slate-100 px-1">{`{{${v}}}`}</code>)}</div>
          {preview && <div className="rounded border border-slate-200 bg-slate-50 p-3 text-xs"><div className="font-semibold">{preview.subject}</div><pre className="mt-2 whitespace-pre-wrap font-sans">{preview.body}</pre></div>}
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
            <thead className="bg-slate-50"><tr><th className="th">Created</th><th className="th">Template</th><th className="th">Recipient</th><th className="th">Subject</th><th className="th">Status</th><th className="th">Attempts</th><th className="th">Error</th><th className="th" /></tr></thead>
            <tbody className="divide-y divide-slate-100">{data.map((e) => (
              <tr key={e.id}><td className="td text-xs whitespace-nowrap">{fmtDateTime(e.created_at)}</td><td className="td text-xs">{e.template_key}</td><td className="td text-xs">{e.recipient}</td><td className="td max-w-xs truncate text-xs">{e.subject}</td>
                <td className="td"><Pill className={tone[e.status]}>{e.status}</Pill>{e.sent_at && <div className="text-[11px] text-slate-500">{fmtDateTime(e.sent_at)}</div>}</td>
                <td className="td text-xs">{e.attempts}/{e.max_attempts}{e.status === 'queued' && e.attempts > 0 && <div className="text-slate-500">next {fmtDateTime(e.next_attempt_at)}</div>}</td>
                <td className="td max-w-xs text-xs text-red-700">{e.last_error}</td>
                <td className="td">{e.status !== 'sent' && <button className="btn-ghost px-2" aria-label="Retry delivery" onClick={async () => { try { await post(`/api/admin/email-logs/${e.id}/retry`); toast('success', 'Requeued'); reload() } catch (err) { toast('error', validationMessage(err)) } }}><RotateCcw className="h-4 w-4" /></button>}</td></tr>
            ))}</tbody>
          </table>
        )}
      </div>
    </>
  )
}
