import { useState } from 'react'
import { ShieldCheck } from 'lucide-react'
import { useAuth } from '../lib/auth'
import { validationMessage } from '../api/client'

export default function Login() {
  const { login } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-slate-900 via-slate-800 to-blue-950 p-4">
      <form className="card w-full max-w-sm space-y-4 p-6" onSubmit={async (e) => {
        e.preventDefault(); setBusy(true); setError(null)
        try { await login(email, password) } catch (err) { setError(validationMessage(err)) } finally { setBusy(false) }
      }}>
        <div className="flex items-center gap-2">
          <ShieldCheck className="h-8 w-8 text-blue-700" />
          <div><h1 className="text-lg font-semibold">OffSec Resource Planner</h1><p className="text-xs text-slate-500">Sign in to continue</p></div>
        </div>
        {error && <div className="rounded border border-red-200 bg-red-50 p-2 text-sm text-red-800" role="alert">{error}</div>}
        <div><label className="label" htmlFor="email">Email</label><input id="email" className="input" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} /></div>
        <div><label className="label" htmlFor="password">Password</label><input id="password" className="input" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} /></div>
        <button className="btn-primary w-full" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
        <p className="text-center text-[11px] text-slate-400">Internal use only. All activity is audited.</p>
      </form>
    </div>
  )
}
