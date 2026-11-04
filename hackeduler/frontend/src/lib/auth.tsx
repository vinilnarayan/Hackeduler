import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { get, post, setCsrfToken, setUnauthorizedHandler } from '../api/client'
import type { User } from '../api/types'

interface AuthCtx {
  user: User | null
  loading: boolean
  login: (email: string, password: string) => Promise<User>
  logout: () => Promise<void>
}

const Ctx = createContext<AuthCtx>(null as unknown as AuthCtx)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setUnauthorizedHandler(() => setUser(null))
    get<{ user: User; csrf_token: string }>('/api/auth/me')
      .then((r) => {
        setCsrfToken(r.csrf_token)
        setUser(r.user)
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

  return <Ctx.Provider value={{ user, loading, login, logout }}>{children}</Ctx.Provider>
}

export const useAuth = () => useContext(Ctx)
