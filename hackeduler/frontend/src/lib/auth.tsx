import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { get, post, setCsrfToken, setUnauthorizedHandler } from '../api/client'
import type { User } from '../api/types'

interface AuthCtx {
  user: User | null
  loading: boolean
  login: (email: string, password: string) => Promise<User>
  logout: () => Promise<void>
  acting: ActingAs | null                 // set while an admin is using "Act as"
  actAs: (userId: string) => Promise<void>
  exitActing: () => Promise<void>
}

export interface ActingAs { admin_name: string | null; admin_email: string | null; expires_at: string }

const Ctx = createContext<AuthCtx>(null as unknown as AuthCtx)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)
  const [acting, setActing] = useState<ActingAs | null>(null)

  useEffect(() => {
    setUnauthorizedHandler(() => setUser(null))
    get<{ user: User; csrf_token: string; acting_as?: ActingAs | null }>('/api/auth/me')
      .then((r) => {
        setCsrfToken(r.csrf_token)
        setUser(r.user)
        setActing(r.acting_as ?? null)
      })
      .catch(() => setUser(null))
      .finally(() => setLoading(false))
  }, [])

  const login = useCallback(async (email: string, password: string) => {
    const r = await post<{ user: User; csrf_token: string }>('/api/auth/login', { email, password })
    setCsrfToken(r.csrf_token)
    setUser(r.user)
    return r.user
  }, [])

  const logout = useCallback(async () => {
    let ssoLogout: string | null = null
    try {
      const r = await post<{ sso_logout_url?: string | null }>('/api/auth/logout')
      ssoLogout = r?.sso_logout_url ?? null
    } finally {
      setCsrfToken(null)
      setUser(null)
    }
    // single logout at the identity provider (only https URLs supplied by our backend)
    if (ssoLogout && /^https:\/\//.test(ssoLogout)) window.location.assign(ssoLogout)
  }, [])

  // Admin "Act as": switch session, then reload so every page starts fresh as the other user (and back again).
  const actAs = useCallback(async (userId: string) => {
    const r = await post<{ csrf_token: string }>(`/api/auth/act-as/${userId}`)
    setCsrfToken(r.csrf_token)
    window.location.assign('/')
  }, [])
  const exitActing = useCallback(async () => {
    const r = await post<{ csrf_token: string }>('/api/auth/act-as/exit')
    setCsrfToken(r.csrf_token)
    window.location.assign('/admin/users')
  }, [])

  return <Ctx.Provider value={{ user, loading, login, logout, acting, actAs, exitActing }}>{children}</Ctx.Provider>
}

export const useAuth = () => useContext(Ctx)
