// Persona switching (no login). One app; the corner switcher puts on any hat
// so the platform can be demoed to a client instantly. The chosen persona
// scopes the worker view (whose tasks/questions) and decides which nav the
// shell shows. The agent itself is named "Shlomi" throughout.

import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'

export const AGENT_NAME = 'Shlomi'

export type Role = 'worker' | 'manager' | 'exec' | 'demo'

export interface Persona {
  role: Role
  /** For the worker role: which team member's identity we're acting as. */
  identity?: string
}

export const ROLE_META: Record<Role, { label: string; blurb: string }> = {
  worker: { label: 'Team member', blurb: 'My tasks & what Shlomi needs from me' },
  manager: { label: 'Manager', blurb: 'Review & approve what Shlomi proposes' },
  exec: { label: 'Executive', blurb: 'Project health & ask Shlomi anything' },
  demo: { label: 'Demo console', blurb: 'Drive the whole platform live' },
}

interface PersonaCtx {
  persona: Persona
  setRole: (role: Role) => void
  setIdentity: (identity: string) => void
}

const Ctx = createContext<PersonaCtx | null>(null)
const KEY = 'aipm.persona'

export function PersonaProvider({ children }: { children: ReactNode }) {
  const [persona, setPersona] = useState<Persona>(() => {
    try {
      const saved = localStorage.getItem(KEY)
      if (saved) {
        const parsed = JSON.parse(saved) as Persona
        // Validate against known roles — a stale/renamed role would otherwise
        // index NAV_BY_ROLE/ROLE_META to undefined and crash at render.
        if (parsed && parsed.role in ROLE_META) {
          return { role: parsed.role, identity: parsed.identity }
        }
      }
    } catch {
      /* ignore malformed storage */
    }
    return { role: 'manager' }
  })

  useEffect(() => {
    try {
      localStorage.setItem(KEY, JSON.stringify(persona))
    } catch {
      /* ignore */
    }
  }, [persona])

  const value = useMemo<PersonaCtx>(
    () => ({
      persona,
      setRole: (role) => setPersona((p) => ({ ...p, role })),
      setIdentity: (identity) => setPersona((p) => ({ ...p, identity })),
    }),
    [persona],
  )

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function usePersona() {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('usePersona must be used within PersonaProvider')
  return ctx
}
