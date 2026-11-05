import { useState } from 'react'
import { ChevronDown, ChevronRight, Plus } from 'lucide-react'
import { del, get, patch, post, validationMessage } from '../../api/client'
import type { Implementation, Product } from '../../api/types'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { Empty, ErrorState, Field, Modal, PageHeader, Pill, Spinner } from '../../components/ui'
import { useToast } from '../../lib/toast'
import { useAsync } from '../../lib/useAsync'

type EditTarget =
  | { kind: 'product'; id?: string; name: string; description: string }
  | { kind: 'implementation'; id?: string; productId: string; productName: string; name: string; description: string }

/** Products group requesters and bookings; implementations are sub-groups within a product. */
export default function Products() {
  const toast = useToast()
  const { data, error, loading, reload } = useAsync<Product[]>(() => get('/api/admin/products'))
  const [open, setOpen] = useState<Record<string, boolean>>({})
  const [edit, setEdit] = useState<EditTarget | null>(null)
  const [remove, setRemove] = useState<{ kind: 'product' | 'implementation'; id: string; name: string } | null>(null)

  const save = async () => {
    if (!edit) return
    const body = { name: edit.name.trim(), description: edit.description.trim() || null }
    try {
      if (edit.kind === 'product') {
        if (edit.id) await patch(`/api/admin/products/${edit.id}`, body); else await post('/api/admin/products', body)
      } else {
        if (edit.id) await patch(`/api/admin/implementations/${edit.id}`, body); else await post(`/api/admin/products/${edit.productId}/implementations`, body)
        setOpen((o) => ({ ...o, [edit.productId]: true }))
      }
      toast('success', `${edit.kind === 'product' ? 'Product' : 'Implementation'} saved`); setEdit(null); reload()
    } catch (e) { toast('error', validationMessage(e)) }
  }
  const toggle = async (kind: 'products' | 'implementations', item: Product | Implementation) => {
    try { await patch(`/api/admin/${kind}/${item.id}`, { is_active: !item.is_active }); reload() } catch (e) { toast('error', validationMessage(e)) }
  }

  return (
    <div className="max-w-5xl">
      <PageHeader title="Products" subtitle="Group requesters and bookings by product, with implementations inside each product. Requesters in the same product can see each other's bookings. Assign people to a product under Users."
        actions={<button className="btn-primary" onClick={() => setEdit({ kind: 'product', name: '', description: '' })}><Plus className="h-4 w-4" />Add product</button>} />
      {error ? <ErrorState message={error} onRetry={reload} /> : loading ? <Spinner /> : !data?.length ? <div className="card"><Empty title="No products yet" hint="Add your first product, then its implementations." /></div> : (
        <div className="space-y-3">
          {data.map((p) => (
            <div key={p.id} className={`card ${p.is_active ? '' : 'opacity-70'}`}>
              <div className="flex flex-wrap items-center gap-3 px-4 py-3">
                <button className="btn-ghost p-1" aria-label={open[p.id] ? 'Collapse' : 'Expand'} aria-expanded={!!open[p.id]} onClick={() => setOpen({ ...open, [p.id]: !open[p.id] })}>
                  {open[p.id] ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                </button>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2"><span className="font-semibold">{p.name}</span>{!p.is_active && <Pill>Inactive</Pill>}</div>
                  {p.description && <div className="text-xs text-slate-500">{p.description}</div>}
                </div>
                <div className="flex gap-3 text-xs text-slate-600"><span>{p.implementations.length} implementation(s)</span><span>{p.users} user(s)</span><span>{p.bookings} booking(s)</span></div>
                <div className="flex gap-1">
                  <button className="btn-secondary" onClick={() => setEdit({ kind: 'implementation', productId: p.id, productName: p.name, name: '', description: '' })}><Plus className="h-4 w-4" />Implementation</button>
                  <button className="btn-secondary" onClick={() => setEdit({ kind: 'product', id: p.id, name: p.name, description: p.description ?? '' })}>Edit</button>
                  <button className="btn-secondary" onClick={() => toggle('products', p)}>{p.is_active ? 'Deactivate' : 'Activate'}</button>
                  <button className="btn-ghost px-2 text-red-700" onClick={() => setRemove({ kind: 'product', id: p.id, name: p.name })}>Delete</button>
                </div>
              </div>
              {open[p.id] && (
                <div className="border-t border-slate-100 bg-slate-50/60">
                  {p.implementations.length === 0 ? <p className="px-12 py-3 text-sm text-slate-500">No implementations yet.</p> : (
                    <table className="min-w-full text-sm"><thead><tr><th className="th pl-12">Implementation</th><th className="th">Users</th><th className="th">Bookings</th><th className="th">Status</th><th className="th" /></tr></thead>
                      <tbody className="divide-y divide-slate-100">{p.implementations.map((i) => (
                        <tr key={i.id} className={i.is_active ? '' : 'opacity-60'}>
                          <td className="td pl-12"><div className="font-medium">{i.name}</div>{i.description && <div className="text-xs text-slate-500">{i.description}</div>}</td>
                          <td className="td tabular-nums">{i.users}</td><td className="td tabular-nums">{i.bookings}</td>
                          <td className="td">{i.is_active ? <Pill className="bg-emerald-100 text-emerald-800">Active</Pill> : <Pill>Inactive</Pill>}</td>
                          <td className="td whitespace-nowrap"><div className="flex gap-1">
                            <button className="btn-secondary" onClick={() => setEdit({ kind: 'implementation', id: i.id, productId: p.id, productName: p.name, name: i.name, description: i.description ?? '' })}>Edit</button>
                            <button className="btn-secondary" onClick={() => toggle('implementations', i)}>{i.is_active ? 'Deactivate' : 'Activate'}</button>
                            <button className="btn-ghost px-2 text-red-700" onClick={() => setRemove({ kind: 'implementation', id: i.id, name: i.name })}>Delete</button>
                          </div></td>
                        </tr>
                      ))}</tbody></table>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
      <Modal open={!!edit} onClose={() => setEdit(null)} size="sm"
        title={edit?.kind === 'product' ? (edit.id ? 'Edit product' : 'Add product') : edit?.id ? 'Edit implementation' : `Add implementation to ${edit?.kind === 'implementation' ? edit.productName : ''}`}
        footer={<><button className="btn-secondary" onClick={() => setEdit(null)}>Cancel</button><button className="btn-primary" disabled={!edit?.name.trim()} onClick={save}>Save</button></>}>
        {edit && <div className="space-y-3">
          <Field label="Name *" htmlFor="pr-n"><input id="pr-n" className="input" maxLength={120} value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} /></Field>
          <Field label="Description" htmlFor="pr-d"><textarea id="pr-d" className="input" maxLength={1000} value={edit.description} onChange={(e) => setEdit({ ...edit, description: e.target.value })} /></Field>
        </div>}
      </Modal>
      <ConfirmDialog open={!!remove} onClose={() => setRemove(null)} title={`Delete ${remove?.name}`} tone="danger" confirmLabel="Delete"
        message={`${remove?.kind === 'product' ? 'The product and its implementations' : 'The implementation'} will be deleted. This is only possible while nothing uses it; otherwise deactivate it instead.`}
        onConfirm={async () => { try { await del(`/api/admin/${remove!.kind === 'product' ? 'products' : 'implementations'}/${remove!.id}`); toast('success', `${remove!.name} deleted`); setRemove(null); reload() } catch (e) { setRemove(null); toast('error', validationMessage(e)) } }} />
    </div>
  )
}
