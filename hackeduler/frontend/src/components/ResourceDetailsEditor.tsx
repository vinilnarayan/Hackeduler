import { useState } from 'react'
import { patch, validationMessage } from '../api/client'
import type { Booking } from '../api/types'
import { validPocEmails } from '../lib/emails'
import { useToast } from '../lib/toast'
import { Field } from './ui'

/** The assigned engineer edits the DETAILS of their own approved booking (never dates, activity, resource or product).
 *  Sends the changed fields plus a required reason; the POC, the engineers and the requester are emailed. */
export function ResourceDetailsEditor({ booking, onCancel, onSaved }: { booking: Booking; onCancel: () => void; onSaved: () => void }) {
  const toast = useToast()
  const [f, setF] = useState({
    application_name: booking.application_name, application_version: booking.application_version, pci: booking.pci_dss_scope ? 'yes' : 'no',
    poc_name: booking.poc_name, poc_email: booking.poc_email, additional_comments: booking.additional_comments ?? '', reason: '',
  })
  const [busy, setBusy] = useState(false)
  const s = (k: keyof typeof f) => (e: React.ChangeEvent<any>) => setF({ ...f, [k]: e.target.value })

  const changes: Record<string, any> = {}
  if (f.application_name !== booking.application_name) changes.application_name = f.application_name.trim()
  if (f.application_version !== booking.application_version) changes.application_version = f.application_version.trim()
  if ((f.pci === 'yes') !== booking.pci_dss_scope) changes.pci_dss_scope = f.pci === 'yes'
  if (f.poc_name !== booking.poc_name) changes.poc_name = f.poc_name.trim()
  if (f.poc_email !== booking.poc_email) changes.poc_email = f.poc_email.trim()
  if ((f.additional_comments || null) !== (booking.additional_comments || null)) changes.additional_comments = f.additional_comments.trim() || null
  const valid = f.application_name.trim() && f.application_version.trim() && f.poc_name.trim() && validPocEmails(f.poc_email)
  const ready = Object.keys(changes).length > 0 && !!valid && !!f.reason.trim()

  async function save(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    try {
      await patch(`/api/resource/bookings/${booking.id}`, { ...changes, reason: f.reason.trim() })
      toast('success', 'Details updated. The POC, the engineers and the requester have been emailed.')
      onSaved()
    } catch (err) { toast('error', validationMessage(err)) } finally { setBusy(false) }
  }

  return (
    <form className="space-y-3 rounded-md border border-slate-200 p-3" onSubmit={save} aria-label="Edit booking details">
      <h3 className="text-sm font-semibold">Edit details</h3>
      <p className="text-xs text-slate-500">Dates, activity, resource and product can only be changed by an administrator. Every change is recorded under your name and the POC, the engineers on the booking and the requester are emailed.</p>
      <div className="grid gap-3 md:grid-cols-3">
        <Field label="Application name" htmlFor="rd-an"><input id="rd-an" className="input" value={f.application_name} onChange={s('application_name')} /></Field>
        <Field label="Version" htmlFor="rd-av"><input id="rd-av" className="input" value={f.application_version} onChange={s('application_version')} /></Field>
        <Field label="PCI DSS scope" htmlFor="rd-pci"><select id="rd-pci" className="input" value={f.pci} onChange={s('pci')}><option value="yes">Yes</option><option value="no">No</option></select></Field>
        <Field label="POC name" htmlFor="rd-pn"><input id="rd-pn" className="input" value={f.poc_name} onChange={s('poc_name')} /></Field>
        <Field label="POC email(s)" htmlFor="rd-pe" hint="Separate several addresses with commas." error={f.poc_email && !validPocEmails(f.poc_email) ? 'Enter valid email address(es).' : undefined}><input id="rd-pe" type="text" inputMode="email" className="input" value={f.poc_email} onChange={s('poc_email')} /></Field>
        <Field label="Comments" htmlFor="rd-c"><input id="rd-c" className="input" maxLength={4000} value={f.additional_comments} onChange={s('additional_comments')} /></Field>
      </div>
      <Field label="Reason for change *" htmlFor="rd-r"><textarea id="rd-r" className="input min-h-16" maxLength={2000} value={f.reason} onChange={s('reason')} /></Field>
      <div className="flex justify-end gap-2">
        <button type="button" className="btn-secondary" onClick={onCancel}>Cancel</button>
        <button className="btn-primary" disabled={busy || !ready}>{busy ? 'Saving…' : 'Save changes'}</button>
      </div>
    </form>
  )
}
