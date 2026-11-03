import { useState } from 'react'
import { Plus } from 'lucide-react'
import { get, patch, post, validationMessage } from '../../api/client'
import type { User } from '../../api/types'
import { Empty, ErrorState, Field, Modal, PageHeader, Pill, Spinner } from '../../components/ui'
import { useAuth } from '../../lib/auth'
import { fmtDateTime } from '../../lib/dates'
import { useToast } from '../../lib/toast'
import { useAsync } from '../../lib/useAsync'

export default function UsersPage() {
  const toast = useToast()
  const { user: me } = useAuth()
  const { data, error, loading, reload } = useAsync<User[]>(() => get('/api/admin/users'))
  const [edit, setEdit] = useState<any>(null)
  const save = async () => {
    try {
      if (edit.id) await patch(`/api/admin/users/${edit.id}`, { full_name: edit.full_name, role: edit.role, ...(edit.password ? { password: edit.password } : {}) })
      else await post('/api/admin/users', { email: edit.email, full_name: edit.full_name, role: edit.role, password: edit.password })
      toast('success', 'User saved'); setEdit(null); reload()
    } catch (e) { toast('error', validationMessage(e)) }
  }
  const toggle = async (u: User) => { try { await patch(`/api/admin/users/${u.id}`, { is_active: !u.is_active }); reload() } catch (e) { toast('error', validationMessage(e)) } }
  return (
    <div>
      <PageHeader title="Users" subtitle="Local accounts (enterprise SSO can be integrated – see docs). Role changes, deactivation and password resets revoke existing sessions."
        actions={<button className="btn-primary" onClick={() => setEdit({ role: 'requester', email: '', full_name: '', password: '' })}><Plus className="h-4 w-4" />Add user</button>} />
      <div className="card overflow-x-auto">
        {error ? <ErrorState message={error} onRetry={reload} /> : loading ? <Spinner /> : !data?.length ? <Empty title="No users" /> : (
          <table className="min-w-full divide-y divide-slate-200">
            <thead className="bg-slate-50"><tr><th className="th">Name</th><th className="th">Email</th><th className="th">Role</th><th className="th">Status</th><th className="th">Last login</th><th className="th" /></tr></thead>
            <tbody className="divide-y divide-slate-100">{data.map((u) => (
              <tr key={u.id}><td className="td font-medium">{u.full_name}</td><td className="td text-xs">{u.email}</td>
                <td className="td"><Pill className={u.role === 'admin' ? 'bg-blue-100 text-blue-800' : ''}>{u.role}</Pill></td>
                <td className="td">{u.is_active ? <Pill className="bg-emerald-100 text-emerald-800">Active</Pill> : <Pill>Disabled</Pill>}</td>
                <td className="td text-xs">{fmtDateTime(u.last_login_at)}</td>
                <td className="td whitespace-nowrap"><div className="flex gap-1"><button className="btn-secondary" onClick={() => setEdit({ ...u, password: '' })}>Edit</button>{u.id !== me?.id && <button className="btn-secondary" onClick={() => toggle(u)}>{u.is_active ? 'Disable' : 'Enable'}</button>}</div></td></tr>
            ))}</tbody>
          </table>
        )}
      </div>
      <Modal open={!!edit} onClose={() => setEdit(null)} size="sm" title={edit?.id ? 'Edit user' : 'Add user'}
        footer={<><button className="btn-secondary" onClick={() => setEdit(null)}>Cancel</button><button className="btn-primary" onClick={save}>Save</button></>}>
        {edit && <div className="space-y-3">
          {!edit.id && <Field label="Email *" htmlFor="u-e"><input id="u-e" type="email" className="input" value={edit.email} onChange={(e) => setEdit({ ...edit, email: e.target.value })} /></Field>}
          <Field label="Full name *" htmlFor="u-n"><input id="u-n" className="input" value={edit.full_name} onChange={(e) => setEdit({ ...edit, full_name: e.target.value })} /></Field>
          <Field label="Role" htmlFor="u-r"><select id="u-r" className="input" disabled={edit.id === me?.id} value={edit.role} onChange={(e) => setEdit({ ...edit, role: e.target.value })}><option value="requester">Requester</option><option value="admin">Admin</option></select></Field>
          <Field label={edit.id ? 'Reset password' : 'Password *'} htmlFor="u-p" hint="Min. 12 characters with 3 of: lowercase, uppercase, digit, symbol."><input id="u-p" type="password" autoComplete="new-password" className="input" value={edit.password} onChange={(e) => setEdit({ ...edit, password: e.target.value })} /></Field>
        </div>}
      </Modal>
    </div>
  )
}
