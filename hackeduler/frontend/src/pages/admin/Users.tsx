import { useMemo, useState } from 'react'
import { Plus, Search } from 'lucide-react'
import { del, get, patch, post, validationMessage } from '../../api/client'
import type { Product, ResourceAdmin, User } from '../../api/types'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { Empty, ErrorState, Field, Modal, PageHeader, Pill, Spinner } from '../../components/ui'
import { useAuth } from '../../lib/auth'
import { fmtDateTime } from '../../lib/dates'
import { useToast } from '../../lib/toast'
import { useAsync } from '../../lib/useAsync'
import { SortTh, useSort } from '../../components/SortTh'

const signInOf = (u: User) => (u.sso_provider_id ? 'SSO' : u.has_password ? 'Password' : 'SSO (not yet signed in)')
const statusOf = (u: User) => (u.deleted_at ? 'Deleted' : u.is_active ? 'Active' : 'Disabled')
const lastMethod = (u: User) => (u.last_login_method ? (u.last_login_method.startsWith('sso:') ? `via SSO (${u.last_login_method.slice(4)})` : 'via password') : '')
/** Everything visible in a row, as one lowercase string, so the search box matches any column. */
const searchText = (u: User) => [
  u.full_name, u.email, u.role, u.is_lead ? 'Lead' : '', u.resource_name, u.product_name, u.products?.map((p) => p.name).join(' '), u.implementation_name,
  u.sso_provider_id ? `SSO ${u.sso_provider_name ?? ''}` : '', u.has_password ? 'Password' : '', signInOf(u), statusOf(u),
  u.deleted_at ? fmtDateTime(u.deleted_at) : '', fmtDateTime(u.last_login_at), lastMethod(u),
].filter(Boolean).join(' ').toLowerCase()
const tally = (users: User[], keys: string[], of: (u: User) => string[]) => keys.map((k) => [k, users.filter((u) => of(u).includes(k)).length] as const)

export default function UsersPage() {
  const toast = useToast()
  const { user: me, actAs: startActAs } = useAuth()
  const [showDeleted, setShowDeleted] = useState(false)
  const { data, error, loading, reload } = useAsync<User[]>(() => get(`/api/admin/users${showDeleted ? '?include_deleted=true' : ''}`), [showDeleted])
  const [q, setQ] = useState('')
  const shown = useMemo(() => {
    const terms = q.toLowerCase().split(/\s+/).filter(Boolean)
    return terms.length ? (data ?? []).filter((u) => { const t = searchText(u); return terms.every((x) => t.includes(x)) }) : (data ?? [])
  }, [data, q])
  const tbl = useSort(shown, { name: (u) => u.full_name, email: (u) => u.email, role: (u) => u.role, product: (u) => u.product_name, signin: signInOf, status: statusOf, last: (u) => u.last_login_at })
  const [remove, setRemove] = useState<User | null>(null)
  const products = useAsync<Product[]>(() => get('/api/admin/products'))
  const resources = useAsync<ResourceAdmin[]>(() => get('/api/admin/resources'))
  const prodOf = (id?: string | null) => products.data?.find((p) => p.id === id)
  const restore = async (u: User) => { try { await post(`/api/admin/users/${u.id}/restore`); toast('success', `${u.full_name} restored (disabled). Enable the account when ready.`); reload() } catch (e) { toast('error', validationMessage(e)) } }
  const [edit, setEdit] = useState<any>(null)
  const actAs = async (u: User) => { try { await startActAs(u.id) } catch (e) { toast('error', validationMessage(e)) } }
  const save = async () => {
    const extraIds: string[] = edit.product_id ? (edit.extra_product_ids ?? []).filter((id: string) => id !== edit.product_id) : []
    try {
      if (edit.id) {
        await patch(`/api/admin/users/${edit.id}`, {
          full_name: edit.full_name, role: edit.role, resource_id: edit.role === 'resource' ? edit.resource_id || null : null, is_lead: edit.role === 'resource' && !!edit.is_lead, ...(edit.password ? { password: edit.password } : {}),
          product_id: edit.product_id || null, implementation_id: edit.implementation_id || null, extra_product_ids: extraIds,
          ...(edit.remove_password ? { remove_password: true } : {}), ...(edit.unlink_sso ? { unlink_sso: true } : {}),
        })
      } else {
        await post('/api/admin/users', { email: edit.email, full_name: edit.full_name, role: edit.role, ...(edit.role === 'resource' ? { resource_id: edit.resource_id || null, is_lead: !!edit.is_lead } : {}), ...(edit.sso_only ? {} : { password: edit.password }),
          product_id: edit.product_id || null, implementation_id: edit.implementation_id || null, extra_product_ids: extraIds })
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
      <div className="mb-3 flex flex-wrap gap-2 text-sm" aria-live="polite" data-testid="user-counts">
        <span className="card px-3 py-1.5"><b className="tabular-nums">{shown.length}</b> {shown.length === 1 ? 'user' : 'users'}{q.trim() && data ? <> of <span className="tabular-nums">{data.length}</span></> : null}</span>
        <span className="card px-3 py-1.5">Role: {tally(shown, ['admin', 'requester', 'resource'], (u) => [u.role]).map(([k, n], i) => <span key={k}>{i > 0 && ' · '}{k[0].toUpperCase() + k.slice(1)} <b className="tabular-nums">{n}</b></span>)} · Leads <b className="tabular-nums">{shown.filter((u) => u.is_lead).length}</b></span>
        <span className="card px-3 py-1.5">Sign-in: {tally(shown, ['SSO', 'Password', 'SSO (not yet signed in)'], (u) => [signInOf(u), ...(u.sso_provider_id && u.has_password ? ['Password'] : [])]).map(([k, n], i) => <span key={k}>{i > 0 && ' · '}{k} <b className="tabular-nums">{n}</b></span>)}</span>
        <span className="card px-3 py-1.5">Status: {tally(shown, ['Active', 'Disabled', ...(showDeleted ? ['Deleted'] : [])], (u) => [statusOf(u)]).map(([k, n], i) => <span key={k}>{i > 0 && ' · '}{k} <b className="tabular-nums">{n}</b></span>)}</span>
      </div>
      <div className="card mb-3 p-3">
        <label className="relative block"><span className="sr-only">Search users</span><Search className="absolute top-2 left-2 h-4 w-4 text-slate-400" /><input className="input pl-8" type="search" placeholder="Search name, email, role, product, sign-in, status, last login…" value={q} onChange={(e) => setQ(e.target.value)} /></label>
      </div>
      <div className="card overflow-x-auto">
        {error ? <ErrorState message={error} onRetry={reload} /> : loading ? <Spinner /> : !data?.length ? <Empty title="No users" /> : !shown.length ? <Empty title="No users match your search" /> : (
          <table className="min-w-full divide-y divide-slate-200">
            <thead className="bg-slate-50"><tr><SortTh label="Name" k="name" sort={tbl.sort} onToggle={tbl.toggle} /><SortTh label="Email" k="email" sort={tbl.sort} onToggle={tbl.toggle} /><SortTh label="Role" k="role" sort={tbl.sort} onToggle={tbl.toggle} /><SortTh label="Product / implementation" k="product" sort={tbl.sort} onToggle={tbl.toggle} /><SortTh label="Sign-in" k="signin" sort={tbl.sort} onToggle={tbl.toggle} /><SortTh label="Status" k="status" sort={tbl.sort} onToggle={tbl.toggle} /><SortTh label="Last login" k="last" sort={tbl.sort} onToggle={tbl.toggle} /><th className="th" /></tr></thead>
            <tbody className="divide-y divide-slate-100">{tbl.sorted.map((u) => (
              <tr key={u.id} className={u.deleted_at ? 'bg-slate-50 opacity-70' : ''}><td className="td font-medium">{u.full_name}</td><td className="td text-xs">{u.email}</td>
                <td className="td"><Pill className={u.role === 'admin' ? 'bg-blue-100 text-blue-800' : u.role === 'resource' ? 'bg-teal-100 text-teal-800' : ''}>{u.role}</Pill>{u.is_lead && <Pill className="ml-1 bg-violet-100 text-violet-800">Lead</Pill>}{u.resource_name && <div className="text-xs text-slate-500">{u.resource_name}</div>}</td>
                <td className="td text-xs">{u.product_name ? <><div className="font-medium">{u.product_name}{(u.extra_product_ids?.length ?? 0) > 0 && <span className="ml-1 font-normal text-slate-600">+ {u.products?.filter((p) => p.id !== u.product_id).map((p) => p.name).join(', ')}</span>}</div><div className="text-slate-500">{u.implementation_name ?? '—'}</div></> : <span className="text-slate-400">—</span>}</td>
                <td className="td"><div className="flex flex-wrap gap-1">
                  {u.sso_provider_id && <Pill className="bg-violet-100 text-violet-800">SSO · {u.sso_provider_name}</Pill>}
                  {u.has_password && <Pill>Password</Pill>}
                  {!u.sso_provider_id && !u.has_password && <Pill className="bg-amber-100 text-amber-800">SSO (not yet signed in)</Pill>}
                </div></td>
                <td className="td">{u.deleted_at ? <Pill className="bg-red-100 text-red-800">Deleted {fmtDateTime(u.deleted_at)}</Pill> : u.is_active ? <Pill className="bg-emerald-100 text-emerald-800">Active</Pill> : <Pill>Disabled</Pill>}</td>
                <td className="td text-xs">{fmtDateTime(u.last_login_at)}{u.last_login_method && <div className="text-slate-500">{lastMethod(u)}</div>}</td>
                <td className="td whitespace-nowrap">{u.deleted_at ? <button className="btn-secondary" onClick={() => restore(u)}>Restore</button> : <div className="flex gap-1"><button className="btn-secondary" onClick={() => setEdit({ ...u, password: '' })}>Edit</button>{u.id !== me?.id && <>{u.is_active && u.role !== 'admin' && <button className="btn-secondary" title="Open the app as this user (recorded in the audit log)" onClick={() => actAs(u)}>Act as</button>}<button className="btn-secondary" onClick={() => toggle(u)}>{u.is_active ? 'Disable' : 'Enable'}</button><button className="btn-ghost px-2 text-red-700" onClick={() => setRemove(u)}>Delete</button></>}</div>}</td></tr>
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
          <Field label="Role" htmlFor="u-r" hint={edit.sso_provider_id ? 'If the provider syncs roles from groups, this is overwritten at the next SSO sign-in.' : undefined}><select id="u-r" className="input" disabled={edit.id === me?.id} value={edit.role} onChange={(e) => setEdit({ ...edit, role: e.target.value })}><option value="requester">Requester</option><option value="resource">Resource (security engineer)</option><option value="admin">Admin</option></select></Field>
          {edit.role === 'resource' && <Field label="Security resource *" htmlFor="u-res" hint="This user sees only the bookings assigned to this resource and can manage its leave. SSO role sync never changes a resource user.">
            <select id="u-res" className="input" value={edit.resource_id ?? ''} onChange={(e) => setEdit({ ...edit, resource_id: e.target.value })}>
              <option value="">— Select —</option>
              {resources.data?.map((r) => <option key={r.id} value={r.id}>{r.display_name} – {r.engineer_name}</option>)}
            </select>
          </Field>}
          {edit.role === 'resource' && <label className="flex items-start gap-2 rounded-md border border-slate-200 p-2 text-sm"><input type="checkbox" className="mt-0.5" checked={!!edit.is_lead} onChange={(e) => setEdit({ ...edit, is_lead: e.target.checked })} /><span><b>Team lead</b><span className="block text-xs text-slate-500">A lead also gets a read-only <i>Team Calendar</i> in their menu, showing every engineer's activity, leave and holidays.</span></span></label>}
          <Field label="Product" htmlFor="u-prod" hint="Primary product. Requesters in the same product can see each other's bookings.">
            <select id="u-prod" className="input" value={edit.product_id ?? ''} onChange={(e) => setEdit({ ...edit, product_id: e.target.value, implementation_id: '', extra_product_ids: (edit.extra_product_ids ?? []).filter((id: string) => id !== e.target.value) })}>
              <option value="">— None —</option>
              {products.data?.filter((p) => p.is_active || p.id === edit.product_id).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </Field>
          {edit.role === 'requester' && edit.product_id && (
            <fieldset className="rounded border border-slate-200 p-2">
              <legend className="px-1 text-sm font-medium">Also has access to</legend>
              <p className="mb-1 text-xs text-slate-500">This person can also book for, and see the bookings of, these products.</p>
              <div className="grid max-h-36 gap-1 overflow-y-auto sm:grid-cols-2">
                {products.data?.filter((p) => p.id !== edit.product_id && (p.is_active || (edit.extra_product_ids ?? []).includes(p.id))).map((p) => (
                  <label key={p.id} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={(edit.extra_product_ids ?? []).includes(p.id)}
                    onChange={(e) => setEdit({ ...edit, extra_product_ids: e.target.checked ? [...(edit.extra_product_ids ?? []), p.id] : (edit.extra_product_ids ?? []).filter((id: string) => id !== p.id) })} />{p.name}</label>
                ))}
              </div>
            </fieldset>
          )}
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
