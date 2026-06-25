// Lightweight toast system. The platform talks to a live LLM, so transient
// failures happen — toasts surface them *kindly* ("Shlomi didn't respond —
// try again") with an optional retry, instead of dumping an error.

import { AnimatePresence, motion } from 'framer-motion'
import { CheckCircle2, Info, X, AlertTriangle } from 'lucide-react'
import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from 'react'
import { cn } from '../lib/cn'

type ToastKind = 'success' | 'error' | 'info'
interface Toast {
  id: number
  kind: ToastKind
  title: string
  description?: string
  action?: { label: string; onClick: () => void }
}

interface ToastCtx {
  push: (t: Omit<Toast, 'id'>) => void
  success: (title: string, description?: string) => void
  error: (title: string, description?: string, action?: Toast['action']) => void
  info: (title: string, description?: string) => void
}

const Ctx = createContext<ToastCtx | null>(null)

const KIND: Record<ToastKind, { icon: typeof Info; cls: string }> = {
  success: { icon: CheckCircle2, cls: 'text-green bg-green-soft' },
  error: { icon: AlertTriangle, cls: 'text-red bg-red-soft' },
  info: { icon: Info, cls: 'text-blue bg-blue-soft' },
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const seq = useRef(0)

  const remove = useCallback((id: number) => setToasts((t) => t.filter((x) => x.id !== id)), [])

  const push = useCallback(
    (t: Omit<Toast, 'id'>) => {
      const id = ++seq.current
      setToasts((prev) => [...prev, { ...t, id }])
      window.setTimeout(() => remove(id), t.action ? 8000 : 4500)
    },
    [remove],
  )

  const value = useMemo<ToastCtx>(
    () => ({
      push,
      success: (title, description) => push({ kind: 'success', title, description }),
      error: (title, description, action) => push({ kind: 'error', title, description, action }),
      info: (title, description) => push({ kind: 'info', title, description }),
    }),
    [push],
  )

  return (
    <Ctx.Provider value={value}>
      {children}
      <div className="pointer-events-none fixed bottom-5 right-5 z-[100] flex w-[360px] max-w-[calc(100vw-2rem)] flex-col gap-2.5">
        <AnimatePresence>
          {toasts.map((t) => {
            const k = KIND[t.kind]
            return (
              <motion.div
                key={t.id}
                layout
                initial={{ opacity: 0, y: 16, scale: 0.96 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, x: 24, scale: 0.96 }}
                transition={{ type: 'spring', stiffness: 420, damping: 32 }}
                className="pointer-events-auto flex items-start gap-3 rounded-2xl border border-line bg-surface p-3.5 shadow-pop"
              >
                <span className={cn('flex size-8 shrink-0 items-center justify-center rounded-lg', k.cls)}>
                  <k.icon className="size-[18px]" />
                </span>
                <div className="min-w-0 flex-1 pt-0.5">
                  <p className="text-[13.5px] font-bold leading-snug text-ink">{t.title}</p>
                  {t.description && <p className="mt-0.5 text-[12.5px] leading-snug text-muted">{t.description}</p>}
                  {t.action && (
                    <button
                      onClick={() => {
                        t.action!.onClick()
                        remove(t.id)
                      }}
                      className="mt-2 text-[12.5px] font-bold text-accent hover:underline"
                    >
                      {t.action.label}
                    </button>
                  )}
                </div>
                <button
                  onClick={() => remove(t.id)}
                  className="rounded-md p-1 text-faint transition-colors hover:bg-surface-2 hover:text-ink"
                  aria-label="Dismiss"
                >
                  <X className="size-4" />
                </button>
              </motion.div>
            )
          })}
        </AnimatePresence>
      </div>
    </Ctx.Provider>
  )
}

export function useToast() {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useToast must be used within ToastProvider')
  return ctx
}
