import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { authApi } from './api'
import { getToken, setToken } from './api/client'
import type { User } from './api/types'

interface AuthContextValue {
  user: User | null
  loading: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function bootstrap() {
      if (!getToken()) {
        setLoading(false)
        return
      }
      try {
        const me = await authApi.me()
        setUser(me)
      } catch {
        setToken(null)
      } finally {
        setLoading(false)
      }
    }
    bootstrap()
  }, [])

  async function login(username: string, password: string) {
    const res = await authApi.login(username, password)
    setToken(res.access_token)
    const me = await authApi.me()
    setUser(me)
  }

  function logout() {
    setToken(null)
    setUser(null)
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}