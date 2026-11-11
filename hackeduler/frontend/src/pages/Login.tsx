import { useEffect, useState } from 'react'
import { KeyRound, ShieldCheck } from 'lucide-react'
import { get, validationMessage } from '../api/client'
import { useAuth } from '../lib/auth'

interface PublicSSO {
  providers: { slug: string; display_name: string; provider_type: string }[]
  local_login_mode: 'all' | 'admins_only' | 'disabled'
  auto_redirect: boolean
}

export const SSO_ERRORS: Record<string, string> = {
  provider_unavailable: 'The sign-in provider is unavailable or not enabled. Try again or contact the OffSec team.',
  session_expired: 'Your sign-in session expired. Please try again.',
  state_mismatch: 'The sign-in request could not be verified. Please try again.',
  idp_error: 'Sign-in was cancelled or refused by the identity provider.',
  token_exchange_failed: 'The identity provider did not complete the sign-in. Please contact an administrator.',
  invalid_token: 'The identity provider returned an invalid sign-in token.',
  email_missing: 'Your identity provider did not supply a verified email address.',
  domain_not_allowed: 'Your email domain is not permitted to use this application.',
  group_not_allowed: 'You are not a member of a group that is permitted to use this application.',
  not_provisioned: 'No account exists for you yet. Ask an OffSec administrator to grant access.',
  account_disabled: 'Your account has been disabled.',
  identity_conflict: 'Your email address is already linked to a different sign-in identity. Contact an administrator.',
  rate_limited: 'Too many sign-in attempts. Please wait a minute and try again.',
  internal_error: 'Sign-in could not be completed because of a server problem. Please contact an administrator; the details are in Admin > Single Sign-On > Sign-ins.',
  login_failed: 'Sign-in failed. Please try again.',
}

const ICON: Record<string, string> = { entra: '▦', okta: '◎', google: 'G', keycloak: '⚿', generic: '⇥' }

export default function Login() {
  const { login } = useAuth()
  const params = new URLSearchParams(window.location.search)
  const ssoError = params.get('sso_error')
  const forceLocal = params.get('local') === '1'
  const [cfg, setCfg] = useState<PublicSSO | null>(null)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(ssoError ? SSO_ERRORS[ssoError] ?? 'Sign-in failed.' : null)
  const [busy, setBusy] = useState(false)
  const [showLocal, setShowLocal] = useState(false)

  useEffect(() => {
    get<PublicSSO>('/api/auth/sso/providers')
      .then((c) => {
        setCfg(c)
        if (c.auto_redirect && !ssoError && !forceLocal) window.location.assign(`/api/auth/sso/${c.providers[0].slug}/login`)
      })
      .catch(() => setCfg({ providers: [], local_login_mode: 'all', auto_redirect: false }))
  }, [])

  const providers = cfg?.providers ?? []
  const mode = cfg?.local_login_mode ?? 'all'
  const localVisible = mode === 'all' || (mode === 'admins_only' && (showLocal || providers.length === 0)) || forceLocal

  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-slate-900 via-slate-800 to-blue-950 p-4">
      <div className="card w-full max-w-sm space-y-4 p-6">
        <div className="flex items-center gap-2">
          <ShieldCheck className="h-8 w-8 text-blue-700" />
          <div><h1 className="text-lg font-semibold">Hackeduler</h1><p className="text-xs text-slate-500">Sign in to continue</p></div>
        </div>
        {error && <div className="rounded border border-red-200 bg-red-50 p-2 text-sm text-red-800" role="alert">{error}</div>}

        {providers.length > 0 && (
          <div className="space-y-2">
            {providers.map((p) => (
              <a key={p.slug} href={`/api/auth/sso/${encodeURIComponent(p.slug)}/login`} className="btn-primary w-full py-2">
                <span aria-hidden className="font-bold">{ICON[p.provider_type] ?? '⇥'}</span>{p.display_name}
              </a>
            ))}
          </div>
        )}

        {providers.length > 0 && localVisible && <div className="flex items-center gap-2 text-xs text-slate-400"><div className="h-px flex-1 bg-slate-200" />or use a password<div className="h-px flex-1 bg-slate-200" /></div>}

        {localVisible ? (
          <form className="space-y-3" onSubmit={async (e) => {
            e.preventDefault(); setBusy(true); setError(null)
            try { await login(email, password); window.history.replaceState({}, '', '/') } catch (err) { setError(validationMessage(err)) } finally { setBusy(false) }
          }}>
            {mode === 'admins_only' && <p className="text-xs text-amber-700">Password sign-in is limited to administrators (break-glass access).</p>}
            <div><label className="label" htmlFor="email">Email</label><input id="email" className="input" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} /></div>
            <div><label className="label" htmlFor="password">Password</label><input id="password" className="input" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} /></div>
            <button className={providers.length ? 'btn-secondary w-full' : 'btn-primary w-full'} disabled={busy}>{busy ? 'Signing in…' : 'Sign in with password'}</button>
          </form>
        ) : null}

        {mode === 'admins_only' && !localVisible && providers.length > 0 && (
          <button className="btn-ghost w-full text-xs" onClick={() => setShowLocal(true)}><KeyRound className="h-3.5 w-3.5" />Administrator password sign-in</button>
        )}
        {cfg && mode === 'disabled' && !forceLocal && providers.length === 0 && (
          <p className="text-sm text-slate-600">No sign-in method is currently available. Contact the OffSec team.</p>
        )}
        <p className="text-center text-[11px] text-slate-400">Internal use only. All activity is audited.</p>
      </div>
    </div>
  )
}
