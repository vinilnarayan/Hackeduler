import { useState } from 'react'
import { Plus } from 'lucide-react'
import { del, get, patch, post, validationMessage } from '../../api/client'
import type { Product, User } from '../../api/types'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { Empty, ErrorState, Field, Modal, PageHeader, Pill, Spinner } from '../../components/ui'
import { useAuth } from '../../lib/auth'
import { fmtDateTime } from '../../lib/dates'
import { useToast } from '../../lib/toast'
import { useAsync } from '../../lib/useAsync'

export default function UsersPage() {
  const toast = useToast()
  const { user: me } = useAuth()
  const [showDeleted, setShowDeleted] = useState(false)
  const { data, error, loading, reload } = useAsync<User[]>(() => get(`/api/admin/users${showDeleted ? '?include_deleted=true' : ''}`), [showDeleted])
  const [remove, setRemove] = useState<User | null>(null)
  const products = useAsync<Product[]>(() => get('/api/admin/products'))
  const prodOf = (id?: string | null) => products.data?.find((p) => p.id === id)
  const restore = async (u: User) => { try { await post(`/api/admin/users/${u.id}/restore`); toast('success', `${u.full_name} restored (disabled). Enable the account when ready.`); reload() } catch (e) { toast('error', validationMessage(e)) } }
  const [edit, setEdit] = useState<any>(null)
  const save = async () => {
    try {
      if (edit.id) {
        await patch(`/api/admin/users/${edit.id}`, {
          full_name: edit.full_name, role: edit.role, ...(edit.password ? { password: edit.password } : {}),
          product_id: edit.product_id || null, implementation_id: edit.implementation_id || null,
          ...(edit.remove_password ? { remove_password: true } : {}), ...(edit.unlink_sso ? { unlink_sso: true } : {}),
        })
      } else {
        await post('/api/admin/users', { email: edit.email, full_name: edit.full_name, role: edit.role, ...(edit.sso_only ? {} : { password: edit.password }),
          product_id: edit.product_id || null, implementation_id: edit.implementation_id || null })
      }
      toast('success', 'User saved'); setEdit(null); reload()
    } catch (e) { toast('error', validationMessage(e)) }
  }
  const toggle = async (u: User) => { try { await patch(`/api/admin/users/${u.id}`, { is_active: !u.is_active }); reload() } catch (e) { toast('error', validationMessage(e)) } }
  return (
    <div>
      <PageHeader title="Users" subtitle="Accounts can sign in with a local password, SSO, or both. SSO accounts are created automatically on first sign-in when provisioning is enabled, or can be pre-created here without a password. Role changes, deactivation and password changes revoke existing sessions."
        actions={<>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={showDeleted} onChange={(e) => setShowDeleted(e.target.checked)} />Show deleted</label>
          <button className="btn-primary" onClick={() => setEdit({ role: 'requester', email: '', full_name: '', password: '', sso_only: true })}><Plus className="h-4 w-4" />Add user</button>
        </>} />
      <div className="card overflow-x-auto">
        {error ? <ErrorState message={error} onRetry={reload} /> : loading ? <Spinner /> : !data?.length ? <Empty title="No users" /> : (
          <table className="min-w-full divide-y divide-slate-200">
            <thead className="bg-slate-50"><tr><th className="th">Name</th><th className="th">Email</th><th className="th">Role</th><th className="th">Product / implementation</th><th className="th">Sign-in</th><th className="th">Status</th><th className="th">Last login</th><th className="th" /></tr></thead>
            <tbody className="divide-y divide-slate-100">{data.map((u) => (
              <tr key={u.id} className={u.deleted_at ? 'bg-slate-50 opacity-70' : ''}><td className="td font-medium">{u.full_name}</td><td className="td text-xs">{u.email}</td>
                <td className="td"><Pill className={u.role === 'admin' ? 'bg-blue-100 text-blue-800' : ''}>{u.role}</Pill></td>
                <td className="td text-xs">{u.product_name ? <><div className="font-medium">{u.product_name}</div><div className="text-slate-500">{u.implementation_name ?? '—'}</div></> : <span className="text-slate-400">—</span>}</td>
                <td className="td"><div className="flex flex-wrap gap-1">
                  {u.sso_provider_id && <Pill className="bg-violet-100 text-violet-800">SSO · {u.sso_provider_name}</Pill>}
                  {u.has_password && <Pill>Password</Pill>}
                  {!u.sso_provider_id && !u.has_password && <Pill className="bg-amber-100 text-amber-800">SSO (not yet signed in)</Pill>}
                </div></td>
                <td className="td">{u.deleted_at ? <Pill className="bg-red-100 text-red-800">Deleted {fmtDateTime(u.deleted_at)}</Pill> : u.is_active ? <Pill className="bg-emerald-100 text-emerald-800">Active</Pill> : <Pill>Disabled</Pill>}</td>
                <td className="td text-xs">{fmtDateTime(u.last_login_at)}{u.last_login_method && <div className="text-slate-500">{u.last_login_method.startsWith('sso:') ? `via SSO (${u.last_login_method.slice(4)})` : 'via password'}</div>}</td>
                <td className="td whitespace-nowrap">{u.deleted_at ? <button className="btn-secondary" onClick={() => restore(u)}>Restore</button> : <div className="flex gap-1"><button className="btn-secondary" onClick={() => setEdit({ ...u, password: '' })}>Edit</button>{u.id !== me?.id && <><button className="btn-secondary" onClick={() => toggle(u)}>{u.is_active ? 'Disable' : 'Enable'}</button><button className="btn-ghost px-2 text-red-700" onClick={() => setRemove(u)}>Delete</button></>}</div>}</td></tr>
            ))}</tbody>
          </table>
        )}
      </div>
      <ConfirmDialog open={!!remove} onClose={() => setRemove(null)} title={`Delete ${remove?.full_name}`} tone="danger" confirmLabel="Delete user"
        message={<div className="space-y-2"><p>{remove?.email} will be signed out and can no longer sign in. The account disappears from the user list and the email address can be used for a new account.</p>
          <p className="text-xs text-slate-600">If this user has bookings or other activity, the record is archived rather than erased so booking history and the audit trail still show who they were. {remove?.sso_provider_id && 'If SSO auto-provisioning is on and they are still allowed in your identity provider, signing in again would create a new account – remove them from the IdP group as well.'}</p></div>}
        onConfirm={async () => { try { const r = await del<any>(`/api/admin/users/${remove!.id}`); toast('success', `${remove!.full_name} deleted${r.mode === 'archived' ? ' (archived with history)' : ''}`); setRemove(null); reload() } catch (e) { toast('error', validationMessage(e)) } }} />
      <Modal open={!!edit} onClose={() => setEdit(null)} size="sm" title={edit?.id ? 'Edit user' : 'Add user'}
        footer={<><button className="btn-secondary" onClick={() => setEdit(null)}>Cancel</button><button className="btn-primary" onClick={save}>Save</button></>}>
        {edit && <div className="space-y-3">
          {!edit.id && <Field label="Email *" htmlFor="u-e" hint="For SSO users this must match the email asserted by the identity provider."><input id="u-e" type="email" className="input" value={edit.email} onChange={(e) => setEdit({ ...edit, email: e.target.value })} /></Field>}
          <Field label="Full name *" htmlFor="u-n"><input id="u-n" className="input" value={edit.full_name} onChange={(e) => setEdit({ ...edit, full_name: e.target.value })} /></Field>
          <Field label="Role" htmlFor="u-r" hint={edit.sso_provider_id ? 'If the provider syncs roles from groups, this is overwritten at the next SSO sign-in.' : undefined}><select id="u-r" className="input" disabled={edit.id === me?.id} value={edit.role} onChange={(e) => setEdit({ ...edit, role: e.target.value })}><option value="requester">Requester</option><option value="admin">Admin</option></select></Field>
          <Field label="Product" htmlFor="u-prod" hint="Requesters in the same product can see each other's bookings.">
            <select id="u-prod" className="input" value={edit.product_id ?? ''} onChange={(e) => setEdit({ ...edit, product_id: e.target.value, implementation_id: '' })}>
              <option value="">— None —</option>
              {products.data?.filter((p) => p.is_active || p.id === edit.product_id).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </Field>
          <Field label="Implementation" htmlFor="u-impl">
            <select id="u-impl" className="input" value={edit.implementation_id ?? ''} disabled={!edit.product_id} onChange={(e) => setEdit({ ...edit, implementation_id: e.target.value })}>
              <option value="">— None —</option>
              {prodOf(edit.product_id)?.implementations.filter((i) => i.is_active || i.id === edit.implementation_id).map((i) => <option key={i.id} value={i.id}>{i.name}</option>)}
            </select>
          </Field>
          {!edit.id && <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={edit.sso_only} onChange={(e) => setEdit({ ...edit, sso_only: e.target.checked })} />SSO only (no local password)</label>}
          {(edit.id || !edit.sso_only) && (
            <Field label={edit.id ? (edit.has_password ? 'Reset password' : 'Set a local password') : 'Password *'} htmlFor="u-p" hint="Min. 12 characters with 3 of: lowercase, uppercase, digit, symbol.">
              <input id="u-p" type="password" autoComplete="new-password" className="input" value={edit.password} disabled={edit.remove_password} onChange={(e) => setEdit({ ...edit, password: e.target.value })} />
            </Field>
          )}
          {edit.id && edit.has_password && edit.sso_provider_id && edit.id !== me?.id && <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={!!edit.remove_password} onChange={(e) => setEdit({ ...edit, remove_password: e.target.checked, password: '' })} />Remove local password (SSO only)</label>}
          {edit.id && edit.sso_provider_id && <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={!!edit.unlink_sso} onChange={(e) => setEdit({ ...edit, unlink_sso: e.target.checked })} />Unlink SSO identity ({edit.sso_provider_name})</label>}
        </div>}
      </Modal>
    </div>
  )
}
