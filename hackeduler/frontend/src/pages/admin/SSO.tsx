import { useEffect, useState } from 'react'
import { AlertTriangle, CheckCircle2, Copy, Info, KeyRound, Plus, ShieldCheck, XCircle } from 'lucide-react'
import { del, get, patch, post, put, validationMessage } from '../../api/client'
import type { SSOProvider } from '../../api/types'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { Empty, ErrorState, Field, Modal, PageHeader, Pill, Spinner } from '../../components/ui'
import { fmtDateTime } from '../../lib/dates'
import { useToast } from '../../lib/toast'
import { useAsync } from '../../lib/useAsync'

type Preset = { label: string; display_name: string; issuer: string; scopes: string; email_claim: string; name_claim: string
  groups_claim: string; token_auth_method: string; rp_initiated_logout: boolean; extra_auth_params?: Record<string, string>; help: string }

interface SSOSettings {
  local_login_mode: 'all' | 'admins_only' | 'disabled'
  effective_local_login_mode: string
  force_local_login_env: boolean
  public_base_url: string | null
  effective_public_base_url: string
  sso_auto_redirect: boolean
  enabled_providers: number
}

const TYPE_LABEL: Record<string, string> = { entra: 'Microsoft Entra ID', okta: 'Okta', google: 'Google Workspace', keycloak: 'Keycloak', generic: 'Generic OIDC' }

export default function SSOPage() {
  const toast = useToast()
  const settings = useAsync<SSOSettings>(() => get('/api/admin/sso/settings'))
  const providers = useAsync<SSOProvider[]>(() => get('/api/admin/sso/providers'))
  const presets = useAsync<Record<string, Preset>>(() => get('/api/admin/sso/presets'))
  const [edit, setEdit] = useState<Partial<SSOProvider> & { client_secret?: string; _new?: boolean } | null>(null)
  const [pickPreset, setPickPreset] = useState(false)
  const [test, setTest] = useState<{ p: SSOProvider; result: any } | null>(null)
  const [remove, setRemove] = useState<SSOProvider | null>(null)
  const [logins, setLogins] = useState<{ p: SSOProvider; rows: any[] } | null>(null)
  const showLogins = async (p: SSOProvider) => { try { setLogins({ p, rows: await get(`/api/admin/sso/providers/${p.id}/recent-logins`) }) } catch (e) { toast('error', validationMessage(e)) } }
  const reloadAll = () => { settings.reload(); providers.reload() }

  const runTest = async (p: SSOProvider) => {
    try { setTest({ p, result: await post(`/api/admin/sso/providers/${p.id}/test`) }); providers.reload() } catch (e) { toast('error', validationMessage(e)) }
  }
  const toggle = async (p: SSOProvider) => {
    try { await patch(`/api/admin/sso/providers/${p.id}`, { enabled: !p.enabled }); toast('success', `${p.display_name} ${p.enabled ? 'disabled' : 'enabled'}`); reloadAll() } catch (e) { toast('error', validationMessage(e)) }
  }
  const fromPreset = (key: string) => {
    const pr = presets.data![key]
    setPickPreset(false)
    setEdit({
      _new: true, provider_type: key as SSOProvider['provider_type'], slug: key === 'generic' ? 'sso' : key, display_name: pr.display_name,
      issuer: pr.issuer, scopes: pr.scopes, email_claim: pr.email_claim, name_claim: pr.name_claim, groups_claim: pr.groups_claim,
      token_auth_method: pr.token_auth_method as SSOProvider['token_auth_method'], rp_initiated_logout: pr.rp_initiated_logout,
      extra_auth_params: pr.extra_auth_params ?? {}, client_id: '', client_secret: '', use_pkce: true, fetch_userinfo: false,
      admin_groups: [], requester_groups: [], allowed_email_domains: [], auto_provision: true, default_role: 'requester',
      sync_role_on_login: key !== 'google', link_existing_by_email: true, clock_skew_seconds: 120, sort_order: 0, enabled: false,
    })
  }

  if (settings.error) return <ErrorState message={settings.error} onRetry={settings.reload} />
  if (!settings.data || !providers.data) return <Spinner />
  return (
    <div className="max-w-6xl space-y-5">
      <PageHeader title="Single Sign-On" subtitle="Configure OpenID Connect identity providers (Microsoft Entra ID, Okta, Google Workspace, Keycloak or any OIDC provider) and the password sign-in policy."
        actions={<button className="btn-primary" onClick={() => setPickPreset(true)}><Plus className="h-4 w-4" />Add identity provider</button>} />
      <PolicyCard s={settings.data} onSaved={reloadAll} />

      <section className="card">
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-2"><h2 className="text-sm font-semibold">Identity providers</h2><span className="text-xs text-slate-500">{settings.data.enabled_providers} enabled</span></div>
        {providers.data.length === 0 ? <Empty title="No identity providers configured" hint="Add a provider, test the connection, then enable it." /> : (
          <div className="overflow-x-auto"><table className="min-w-full divide-y divide-slate-200">
            <thead className="bg-slate-50"><tr><th className="th">Provider</th><th className="th">Type</th><th className="th">Issuer</th><th className="th">Status</th><th className="th">Last test</th><th className="th">Linked users</th><th className="th" /></tr></thead>
            <tbody className="divide-y divide-slate-100">{providers.data.map((p) => (
              <tr key={p.id}>
                <td className="td"><div className="font-medium">{p.display_name}</div><div className="font-mono text-xs text-slate-500">{p.slug}</div></td>
                <td className="td text-xs">{TYPE_LABEL[p.provider_type]}</td>
                <td className="td max-w-xs truncate font-mono text-xs" title={p.issuer}>{p.issuer}</td>
                <td className="td">{p.enabled ? <Pill className="bg-emerald-100 text-emerald-800">Enabled</Pill> : <Pill>Disabled</Pill>}{!p.has_client_secret && p.token_auth_method !== 'none' && <div className="mt-1"><Pill className="bg-amber-100 text-amber-800">No secret</Pill></div>}</td>
                <td className="td text-xs">{p.last_test_ok === null ? <span className="text-slate-400">Not tested</span> : p.last_test_ok ? <span className="text-emerald-700">✓ Passed</span> : <span className="text-red-700">✗ Failed</span>}<div className="text-slate-400">{fmtDateTime(p.last_tested_at)}</div></td>
                <td className="td text-sm tabular-nums">{p.linked_users}</td>
                <td className="td whitespace-nowrap"><div className="flex gap-1">
                  <button className="btn-secondary" onClick={() => runTest(p)}>Test</button>
                  <button className="btn-secondary" onClick={() => showLogins(p)}>Sign-ins</button>
                  <button className="btn-secondary" onClick={() => setEdit({ ...p, client_secret: '' })}>Edit</button>
                  <button className={p.enabled ? 'btn-secondary' : 'btn-success'} onClick={() => toggle(p)}>{p.enabled ? 'Disable' : 'Enable'}</button>
                  <button className="btn-ghost px-2 text-red-700" onClick={() => setRemove(p)}>Delete</button>
                </div></td>
              </tr>
            ))}</tbody>
          </table></div>
        )}
      </section>

      <Modal open={pickPreset} onClose={() => setPickPreset(false)} title="Choose your identity provider" size="md">
        <div className="grid gap-2 sm:grid-cols-2">
          {presets.data && Object.entries(presets.data).map(([k, pr]) => (
            <button key={k} className="card p-3 text-left hover:border-blue-500 hover:bg-blue-50" onClick={() => fromPreset(k)}>
              <div className="font-medium">{pr.label}</div><div className="mt-1 line-clamp-2 text-xs text-slate-500">{pr.issuer}</div>
            </button>
          ))}
        </div>
      </Modal>

      {edit && <ProviderForm initial={edit} preset={presets.data?.[edit.provider_type ?? 'generic']} baseUrl={settings.data.effective_public_base_url}
        onClose={() => setEdit(null)} onSaved={(p, wasNew) => { setEdit(null); reloadAll(); toast('success', wasNew ? 'Provider saved (disabled). Test it, then enable it.' : 'Provider updated'); if (wasNew) runTest(p) }} />}

      <Modal open={!!test} onClose={() => setTest(null)} size="lg" title={`Connection test – ${test?.p.display_name}`}
        footer={test && !test.p.enabled && test.result.ok ? <button className="btn-success" onClick={async () => { await toggle(test.p); setTest(null) }}>Enable provider</button> : undefined}>
        {test && <div className="space-y-3 text-sm">
          <div className={`flex items-center gap-2 rounded p-2 font-medium ${test.result.ok ? 'bg-emerald-50 text-emerald-800' : 'bg-red-50 text-red-800'}`}>{test.result.ok ? <CheckCircle2 className="h-4 w-4" /> : <XCircle className="h-4 w-4" />}{test.result.ok ? 'Configuration looks good' : 'Problems found'}</div>
          <ul className="space-y-1">{test.result.checks.map((c: any, i: number) => (
            <li key={i} className="flex items-start gap-2">{c.level === 'ok' ? <CheckCircle2 className="mt-0.5 h-4 w-4 text-emerald-600" /> : c.level === 'warning' ? <AlertTriangle className="mt-0.5 h-4 w-4 text-amber-600" /> : <XCircle className="mt-0.5 h-4 w-4 text-red-600" />}
              <div><div className="font-medium">{c.name}</div>{c.detail && <div className="text-xs break-all text-slate-600">{c.detail}</div>}</div></li>
          ))}</ul>
          {test.result.metadata?.authorization_endpoint && <div className="rounded bg-slate-50 p-2 font-mono text-[11px] break-all">{Object.entries(test.result.metadata).filter(([, v]) => v).map(([k, v]) => <div key={k}><span className="text-slate-500">{k}:</span> {String(v)}</div>)}</div>}
          <p className="text-xs text-slate-500">The test checks discovery, issuer and signing keys. To verify the full sign-in (client secret, redirect URI, group claims), enable the provider and sign in from a private browser window.</p>
        </div>}
      </Modal>

      <Modal open={!!logins} onClose={() => setLogins(null)} size="xl" title={`Recent sign-ins – ${logins?.p.display_name}`}>
        <p className="mb-3 text-xs text-slate-600">Shows what the identity provider sent at each sign-in. To grant Admin via SSO, copy a value from <b>Groups received</b> (Entra ID: group Object IDs or app-role values) into the provider's <b>Admin groups</b>. If "Groups claim" says <b>missing</b>, configure a groups claim at the IdP (Entra: Token configuration → Add groups claim) – until then roles are taken from the Users page.</p>
        {!logins?.rows.length ? <Empty title="No SSO sign-ins yet" /> : (
          <div className="overflow-x-auto"><table className="min-w-full divide-y divide-slate-200 text-xs">
            <thead className="bg-slate-50"><tr><th className="th">When</th><th className="th">User</th><th className="th">Result</th><th className="th">Groups claim</th><th className="th">Groups received</th><th className="th">Role</th></tr></thead>
            <tbody className="divide-y divide-slate-100">{logins.rows.map((l, i) => (
              <tr key={i} className="align-top"><td className="td whitespace-nowrap">{fmtDateTime(l.at)}</td><td className="td">{l.email ?? '—'}</td>
                <td className="td">{l.ok ? <span className="text-emerald-700">✓ Signed in{l.provisioned ? ' (new account)' : ''}</span> : <span className="text-red-700">✗ {l.error_code}<div className="max-w-xs break-words text-slate-500">{l.error_detail}</div></span>}</td>
                <td className="td">{!l.ok || l.groups_claim_present == null ? '—' : l.groups_claim_present ? 'present' : <span className="font-medium text-amber-700">missing</span>}</td>
                <td className="td max-w-sm font-mono break-all">{(l.groups_received ?? []).map((g: string) => <div key={g} className={(l.groups_matched ?? []).map((x: string) => x.toLowerCase()).includes(g.toLowerCase()) ? 'font-bold text-emerald-700' : ''}>{g}</div>)}</td>
                <td className="td">{l.role}{l.role_changed && <div className="text-amber-700">changed {l.role_changed.from} → {l.role_changed.to}</div>}{l.role_sync_skipped && <div className="text-slate-500">kept: {l.role_sync_skipped}</div>}</td></tr>
            ))}</tbody>
          </table></div>
        )}
      </Modal>

      <ConfirmDialog open={!!remove} onClose={() => setRemove(null)} title={`Delete ${remove?.display_name}`} tone="danger" confirmLabel="Delete provider"
        message={<>Users linked to this provider ({remove?.linked_users}) will be unlinked. SSO-only accounts will not be able to sign in until linked to another provider or given a password. Consider <b>disabling</b> instead.</>}
        onConfirm={async () => { try { const r = await del<any>(`/api/admin/sso/providers/${remove!.id}`); toast('success', `Provider deleted${r.unlinked_sso_only_users ? ` – ${r.unlinked_sso_only_users} SSO-only user(s) can no longer sign in` : ''}`); setRemove(null); reloadAll() } catch (e) { toast('error', validationMessage(e)) } }} />
    </div>
  )
}

function PolicyCard({ s, onSaved }: { s: SSOSettings; onSaved: () => void }) {
  const toast = useToast()
  const [mode, setMode] = useState(s.local_login_mode)
  const [base, setBase] = useState(s.public_base_url ?? '')
  const [auto, setAuto] = useState(s.sso_auto_redirect)
  useEffect(() => { setMode(s.local_login_mode); setBase(s.public_base_url ?? ''); setAuto(s.sso_auto_redirect) }, [s])
  const save = async () => {
    try { await put('/api/admin/sso/settings', { local_login_mode: mode, public_base_url: base.trim() || null, sso_auto_redirect: auto }); toast('success', 'Sign-in policy saved'); onSaved() }
    catch (e) { toast('error', validationMessage(e)) }
  }
  const opts = [
    { v: 'all', t: 'All users', d: 'Users can sign in with a password or SSO.' },
    { v: 'admins_only', t: 'Administrators only (recommended with SSO)', d: 'Requesters must use SSO. Local admin passwords remain as break-glass access.' },
    { v: 'disabled', t: 'Disabled – SSO only', d: 'Nobody can sign in with a password. Requires that you have signed in as an admin via SSO.' },
  ] as const
  return (
    <section className="card space-y-4 p-4">
      <h2 className="flex items-center gap-2 text-sm font-semibold"><KeyRound className="h-4 w-4" />Sign-in policy</h2>
      {s.force_local_login_env && <div className="flex items-start gap-2 rounded border border-amber-300 bg-amber-50 p-2 text-xs text-amber-900"><AlertTriangle className="h-4 w-4 shrink-0" />The server environment variable <code>HACKEDULER_FORCE_LOCAL_LOGIN=true</code> is set (break-glass): password sign-in is currently allowed for everyone regardless of this setting.</div>}
      <fieldset><legend className="label">Password sign-in</legend>
        <div className="grid gap-2 md:grid-cols-3">{opts.map((o) => (
          <label key={o.v} className={`flex cursor-pointer gap-2 rounded-md border p-3 text-sm ${mode === o.v ? 'border-blue-600 bg-blue-50' : 'border-slate-200'}`}>
            <input type="radio" name="mode" className="mt-0.5" checked={mode === o.v} onChange={() => setMode(o.v)} />
            <span><span className="font-medium">{o.t}</span><span className="block text-xs text-slate-600">{o.d}</span></span>
          </label>
        ))}</div>
      </fieldset>
      <div className="grid gap-3 md:grid-cols-2">
        <Field label="Public application URL" htmlFor="pbu" hint={`Used to build redirect URIs. Currently: ${s.effective_public_base_url}`}>
          <input id="pbu" className="input" placeholder="https://hackeduler.example.com" value={base} onChange={(e) => setBase(e.target.value)} />
        </Field>
        <label className="flex items-start gap-2 pt-5 text-sm"><input type="checkbox" className="mt-0.5" checked={auto} onChange={(e) => setAuto(e.target.checked)} />
          <span>Skip the sign-in page and go straight to the identity provider when SSO is the only method and one provider is enabled<span className="block text-xs text-slate-500">Break-glass: <code>/login?local=1</code> still shows the page.</span></span></label>
      </div>
      <div className="flex justify-end"><button className="btn-primary" onClick={save}>Save policy</button></div>
    </section>
  )
}

const lines = (v?: string[]) => (v ?? []).join('\n')
const toList = (s: string) => s.split(/[\n,]+/).map((x) => x.trim()).filter(Boolean)
const paramsToText = (o?: Record<string, string>) => Object.entries(o ?? {}).map(([k, v]) => `${k}=${v}`).join('\n')
const textToParams = (s: string) => Object.fromEntries(s.split('\n').map((l) => l.trim()).filter(Boolean).map((l) => { const i = l.indexOf('='); return i < 0 ? [l, ''] : [l.slice(0, i).trim(), l.slice(i + 1).trim()] }))

function ProviderForm({ initial, preset, baseUrl, onClose, onSaved }: {
  initial: Partial<SSOProvider> & { client_secret?: string; _new?: boolean }; preset?: Preset; baseUrl: string
  onClose: () => void; onSaved: (p: SSOProvider, wasNew: boolean) => void
}) {
  const toast = useToast()
  const [f, setF] = useState<any>({ ...initial, admin_groups_t: lines(initial.admin_groups), requester_groups_t: lines(initial.requester_groups),
    domains_t: lines(initial.allowed_email_domains), params_t: paramsToText(initial.extra_auth_params), clear_secret: false })
  const [busy, setBusy] = useState(false)
  const [advanced, setAdvanced] = useState(false)
  const isNew = !!initial._new
  const set = (k: string) => (e: React.ChangeEvent<any>) => setF({ ...f, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.type === 'number' ? Number(e.target.value) : e.target.value })
  const redirect = initial.redirect_uri && !isNew ? initial.redirect_uri : `${baseUrl}/api/auth/sso/${f.slug || '<id>'}/callback`

  const save = async () => {
    setBusy(true)
    const body: Record<string, any> = {
      display_name: f.display_name, provider_type: f.provider_type, sort_order: f.sort_order ?? 0, issuer: f.issuer?.trim(),
      discovery_url: f.discovery_url || null, authorization_endpoint: f.authorization_endpoint || null, token_endpoint: f.token_endpoint || null,
      jwks_uri: f.jwks_uri || null, userinfo_endpoint: f.userinfo_endpoint || null, end_session_endpoint: f.end_session_endpoint || null,
      client_id: f.client_id?.trim(), token_auth_method: f.token_auth_method, scopes: f.scopes, extra_auth_params: textToParams(f.params_t),
      use_pkce: f.use_pkce, fetch_userinfo: f.fetch_userinfo, rp_initiated_logout: f.rp_initiated_logout, email_claim: f.email_claim,
      name_claim: f.name_claim, groups_claim: f.groups_claim ?? '', admin_groups: toList(f.admin_groups_t), requester_groups: toList(f.requester_groups_t),
      allowed_email_domains: toList(f.domains_t), auto_provision: f.auto_provision, default_role: f.default_role,
      sync_role_on_login: f.sync_role_on_login, link_existing_by_email: f.link_existing_by_email, clock_skew_seconds: f.clock_skew_seconds,
    }
    if (f.client_secret) body.client_secret = f.client_secret
    if (f.clear_secret) body.clear_client_secret = true
    try {
      const p = isNew ? await post<SSOProvider>('/api/admin/sso/providers', { ...body, slug: f.slug, enabled: false }) : await patch<SSOProvider>(`/api/admin/sso/providers/${initial.id}`, body)
      onSaved(p, isNew)
    } catch (e) { toast('error', validationMessage(e)) } finally { setBusy(false) }
  }

  return (
    <Modal open onClose={onClose} size="xl" title={isNew ? `New provider – ${TYPE_LABEL[f.provider_type]}` : `Edit ${initial.display_name}`}
      footer={<><button className="btn-secondary" onClick={onClose}>Cancel</button><button className="btn-primary" disabled={busy || !f.slug || !f.display_name || !f.issuer || !f.client_id} onClick={save}>{busy ? 'Saving…' : isNew ? 'Save & test' : 'Save'}</button></>}>
      <div className="space-y-5 text-sm">
        {preset?.help && <div className="flex gap-2 rounded-md border border-blue-200 bg-blue-50 p-3 text-xs text-blue-900"><Info className="h-4 w-4 shrink-0" /><span>{preset.help}</span></div>}
        <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
          <div className="label">Redirect URI – register this exact value at your identity provider</div>
          <div className="flex items-center gap-2"><code className="flex-1 break-all text-xs">{redirect}</code>
            <button type="button" className="btn-secondary px-2 py-1 text-xs" onClick={() => { navigator.clipboard?.writeText(redirect); toast('info', 'Redirect URI copied') }}><Copy className="h-3.5 w-3.5" />Copy</button></div>
          {!redirect.startsWith('https://') && <p className="mt-1 text-xs text-amber-700">Most providers require HTTPS redirect URIs in production. Set the Public application URL in the sign-in policy.</p>}
        </div>

        <Section title="General">
          <Field label="Identifier *" htmlFor="p-slug" hint="Lowercase letters, digits, hyphens. Part of the redirect URI – cannot be changed later."><input id="p-slug" className="input font-mono" disabled={!isNew} value={f.slug ?? ''} onChange={set('slug')} /></Field>
          <Field label="Button label *" htmlFor="p-dn"><input id="p-dn" className="input" value={f.display_name ?? ''} onChange={set('display_name')} /></Field>
          <Field label="Provider type" htmlFor="p-type"><select id="p-type" className="input" value={f.provider_type} onChange={set('provider_type')}>{Object.entries(TYPE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
        </Section>

        <Section title="Connection">
          <div className="md:col-span-2"><Field label="Issuer URL *" htmlFor="p-iss" hint="Endpoints are discovered from <issuer>/.well-known/openid-configuration"><input id="p-iss" className="input font-mono text-xs" value={f.issuer ?? ''} onChange={set('issuer')} /></Field></div>
          <Field label="Client ID *" htmlFor="p-cid"><input id="p-cid" className="input font-mono text-xs" autoComplete="off" value={f.client_id ?? ''} onChange={set('client_id')} /></Field>
          <Field label="Client secret" htmlFor="p-sec" hint={initial.has_client_secret ? 'A secret is stored (encrypted). Leave blank to keep it.' : 'Stored encrypted. Never displayed again after saving.'}>
            <input id="p-sec" type="password" className="input" autoComplete="new-password" placeholder={initial.has_client_secret ? '•••••••• (unchanged)' : ''} value={f.client_secret ?? ''} onChange={set('client_secret')} disabled={f.clear_secret} />
            {initial.has_client_secret && <label className="mt-1 flex items-center gap-1.5 text-xs"><input type="checkbox" checked={f.clear_secret} onChange={set('clear_secret')} />Remove stored secret</label>}
          </Field>
          <Field label="Client authentication" htmlFor="p-am"><select id="p-am" className="input" value={f.token_auth_method} onChange={set('token_auth_method')}><option value="client_secret_post">client_secret_post</option><option value="client_secret_basic">client_secret_basic</option><option value="none">none (public client + PKCE)</option></select></Field>
          <Field label="Scopes" htmlFor="p-sc"><input id="p-sc" className="input font-mono text-xs" value={f.scopes ?? ''} onChange={set('scopes')} /></Field>
        </Section>

        <Section title="Claims & role mapping">
          <Field label="Email claim(s)" htmlFor="p-ec" hint="Comma-separated fallbacks, first valid one wins"><input id="p-ec" className="input font-mono text-xs" value={f.email_claim ?? ''} onChange={set('email_claim')} /></Field>
          <Field label="Name claim" htmlFor="p-nc"><input id="p-nc" className="input font-mono text-xs" value={f.name_claim ?? ''} onChange={set('name_claim')} /></Field>
          <Field label="Groups / roles claim" htmlFor="p-gc" hint="e.g. groups, roles, realm_access.roles (dotted = nested)"><input id="p-gc" className="input font-mono text-xs" value={f.groups_claim ?? ''} onChange={set('groups_claim')} /></Field>
          <Field label="Admin groups" htmlFor="p-ag" hint="One per line. Members become Admins (Entra: group Object ID or app role value)."><textarea id="p-ag" className="input min-h-20 font-mono text-xs" value={f.admin_groups_t} onChange={set('admin_groups_t')} /></Field>
          <Field label="Allowed requester groups" htmlFor="p-rg" hint="One per line. If set, only members (or admins) may sign in. Empty = anyone in the directory."><textarea id="p-rg" className="input min-h-20 font-mono text-xs" value={f.requester_groups_t} onChange={set('requester_groups_t')} /></Field>
          <Field label="Allowed email domains" htmlFor="p-dom" hint="One per line, e.g. example.com. Empty = any."><textarea id="p-dom" className="input min-h-20 font-mono text-xs" value={f.domains_t} onChange={set('domains_t')} /></Field>
          <Field label="Role when no admin group matches" htmlFor="p-dr"><select id="p-dr" className="input" value={f.default_role} onChange={set('default_role')}><option value="requester">Requester</option><option value="admin">Admin (requires a group or domain restriction)</option></select></Field>
        </Section>

        <Section title="Provisioning">
          <Check label="Create accounts automatically on first sign-in" hint="Off = an admin must pre-create the user under Users (password optional)." checked={f.auto_provision} onChange={set('auto_provision')} />
          <Check label="Update the role from IdP groups at every sign-in" hint="Applies only when Admin groups are set AND the token contains the groups claim; otherwise the role set in Users is kept. Off = roles always managed in this app. The last active admin is never demoted." checked={f.sync_role_on_login} onChange={set('sync_role_on_login')} />
          <Check label="Link existing accounts by email" hint="Lets current local users switch to SSO. Accounts already linked to another identity are never re-linked." checked={f.link_existing_by_email} onChange={set('link_existing_by_email')} />
          <Check label="Sign out of the identity provider on logout" hint="RP-initiated logout via the provider's end_session_endpoint." checked={f.rp_initiated_logout} onChange={set('rp_initiated_logout')} />
        </Section>

        <button type="button" className="btn-ghost text-xs" onClick={() => setAdvanced(!advanced)}>{advanced ? '▾' : '▸'} Advanced settings</button>
        {advanced && (
          <Section title="Advanced">
            <Check label="Use PKCE (S256)" hint="Strongly recommended; keep on unless your IdP rejects it." checked={f.use_pkce} onChange={set('use_pkce')} />
            <Check label="Fetch claims from the userinfo endpoint" hint="Use when groups/email are not in the ID token." checked={f.fetch_userinfo} onChange={set('fetch_userinfo')} />
            <Field label="Clock skew tolerance (seconds)" htmlFor="p-cs"><input id="p-cs" type="number" min={0} max={600} className="input w-32" value={f.clock_skew_seconds} onChange={set('clock_skew_seconds')} /></Field>
            <Field label="Login button order" htmlFor="p-so"><input id="p-so" type="number" min={0} className="input w-32" value={f.sort_order ?? 0} onChange={set('sort_order')} /></Field>
            <Field label="Extra authorization parameters" htmlFor="p-xp" hint="key=value per line, e.g. prompt=select_account, domain_hint=example.com, hd=example.com"><textarea id="p-xp" className="input min-h-16 font-mono text-xs" value={f.params_t} onChange={set('params_t')} /></Field>
            <Field label="Discovery URL override" htmlFor="p-du"><input id="p-du" className="input font-mono text-xs" value={f.discovery_url ?? ''} onChange={set('discovery_url')} /></Field>
            {(['authorization_endpoint', 'token_endpoint', 'jwks_uri', 'userinfo_endpoint', 'end_session_endpoint'] as const).map((k) => (
              <Field key={k} label={`${k.replace(/_/g, ' ')} override`} htmlFor={`p-${k}`}><input id={`p-${k}`} className="input font-mono text-xs" placeholder="(discovered)" value={f[k] ?? ''} onChange={set(k)} /></Field>
            ))}
          </Section>
        )}
        <p className="flex items-center gap-1.5 text-xs text-slate-500"><ShieldCheck className="h-3.5 w-3.5" />Every change is recorded in the audit log. Secrets are never written to the log.</p>
      </div>
    </Modal>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return <fieldset className="space-y-2"><legend className="mb-2 text-xs font-semibold tracking-wide text-slate-500 uppercase">{title}</legend><div className="grid gap-3 md:grid-cols-3">{children}</div></fieldset>
}

function Check({ label, hint, checked, onChange }: { label: string; hint?: string; checked: boolean; onChange: (e: React.ChangeEvent<HTMLInputElement>) => void }) {
  return <label className="flex items-start gap-2 rounded-md border border-slate-200 p-2"><input type="checkbox" className="mt-0.5" checked={!!checked} onChange={onChange} /><span><span className="font-medium">{label}</span>{hint && <span className="block text-xs text-slate-500">{hint}</span>}</span></label>
}
