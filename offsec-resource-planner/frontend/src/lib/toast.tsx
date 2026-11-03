import { createContext, useCallback, useContext, useState, type ReactNode } from 'react'
import { CheckCircle2, XCircle, Info, X } from 'lucide-react'

type Kind = 'success' | 'error' | 'info'
interface Toast { id: number; kind: Kind; message: string }
const Ctx = createContext<(kind: Kind, message: string) => void>(() => {})

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const push = useCallback((kind: Kind, message: string) => {
    const id = Date.now() + Math.random()
    setToasts((t) => [...t, { id, kind, message }])
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), kind === 'error' ? 8000 : 4500)
  }, [])
  const Icon = { success: CheckCircle2, error: XCircle, info: Info }
  const color = { success: 'border-emerald-500', error: 'border-red-500', info: 'border-blue-500' }
  return (
    <Ctx.Provider value={push}>
      {children}
      <div className="fixed right-4 bottom-4 z-[100] flex w-[min(24rem,calc(100vw-2rem))] flex-col gap-2" role="status" aria-live="polite">
        {toasts.map((t) => {
          const I = Icon[t.kind]
          return (
            <div key={t.id} className={`card flex items-start gap-2 border-l-4 p-3 text-sm ${color[t.kind]}`}>
              <I className={`mt-0.5 h-4 w-4 shrink-0 ${t.kind === 'error' ? 'text-red-600' : t.kind === 'success' ? 'text-emerald-600' : 'text-blue-600'}`} />
              <div className="flex-1 break-words">{t.message}</div>
              <button aria-label="Dismiss notification" className="text-slate-400 hover:text-slate-600" onClick={() => setToasts((x) => x.filter((y) => y.id !== t.id))}>
                <X className="h-4 w-4" />
              </button>
            </div>
          )
        })}
      </div>
    </Ctx.Provider>
  )
}

export const useToast = () => useContext(Ctx)
