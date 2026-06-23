// The "You are: …" hat switcher. No login — picking a role navigates to that
// role's home, so a presenter can show any perspective instantly. For the
// worker role you also choose which team member you're standing in for.

import { AnimatePresence, motion } from 'framer-motion'
import { Briefcase, Check, ChevronDown, HardHat, LineChart, MonitorPlay } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { cn } from '../../lib/cn'
import { personLabel } from '../../lib/format'
import { ROLE_META, usePersona, type Role } from '../../lib/persona'
import { useProject } from '../../lib/queries'
import { Avatar } from '../ui'

const ROLE_ICON: Record<Role, typeof HardHat> = {
  worker: HardHat,
  manager: Briefcase,
  exec: LineChart,
  demo: MonitorPlay,
}
const ROLE_ROUTE: Record<Role, string> = {
  worker: '/worker',
  manager: '/manager',
  exec: '/exec',
  demo: '/demo',
}

export function PersonaSwitcher() {
  const { persona, setRole, setIdentity } = usePersona()
  const { data: project } = useProject()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const team = project?.team ?? []

  useEffect(() => {
    if (!open) return
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setOpen(false)
        triggerRef.current?.focus()
      }
    }
    document.addEventListener('mousedown', onClick)
    document.addEventListener('keydown', onKey)
    // Move focus into the menu so keyboard users can act on it immediately.
    menuRef.current?.querySelector<HTMLButtonElement>('button')?.focus()
    return () => {
      document.removeEventListener('mousedown', onClick)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const Icon = ROLE_ICON[persona.role]
  const choose = (role: Role) => {
    setRole(role)
    navigate(ROLE_ROUTE[role])
    setOpen(false)
  }

  return (
    <div className="relative" ref={ref}>
      <button
        ref={triggerRef}
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Switch perspective"
        className={cn(
          'flex items-center gap-2.5 rounded-xl border border-line bg-surface py-1.5 pl-2.5 pr-2 transition-colors hover:bg-surface-2',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40',
          open && 'bg-surface-2',
        )}
      >
        <span className="flex size-7 items-center justify-center rounded-lg bg-accent-soft text-accent">
          <Icon className="size-4" />
        </span>
        <span className="text-left leading-tight">
          <span className="block text-[10px] font-semibold uppercase tracking-wide text-faint">Viewing as</span>
          <span className="block text-[13px] font-bold text-ink">
            {ROLE_META[persona.role].label}
            {persona.role === 'worker' && persona.identity ? ` · ${personLabel(persona.identity)}` : ''}
          </span>
        </span>
        <ChevronDown className={cn('size-4 text-faint transition-transform', open && 'rotate-180')} />
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            ref={menuRef}
            role="menu"
            aria-label="Switch perspective"
            initial={{ opacity: 0, y: -6, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -6, scale: 0.98 }}
            transition={{ duration: 0.14 }}
            className="absolute right-0 z-50 mt-2 w-72 origin-top-right rounded-2xl border border-line bg-surface p-1.5 shadow-pop"
          >
            <p className="px-3 pb-1.5 pt-2 text-[10px] font-semibold uppercase tracking-wide text-faint">
              Switch perspective
            </p>
            {(Object.keys(ROLE_META) as Role[]).map((role) => {
              const RIcon = ROLE_ICON[role]
              const active = persona.role === role
              return (
                <button
                  key={role}
                  role="menuitem"
                  onClick={() => choose(role)}
                  className={cn(
                    'flex w-full items-center gap-3 rounded-xl px-2.5 py-2 text-left transition-colors',
                    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40',
                    active ? 'bg-accent-soft' : 'hover:bg-surface-2',
                  )}
                >
                  <span
                    className={cn(
                      'flex size-8 items-center justify-center rounded-lg',
                      active ? 'bg-accent text-accent-ink' : 'bg-surface-2 text-ink-soft',
                    )}
                  >
                    <RIcon className="size-4" />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-[13px] font-bold text-ink">{ROLE_META[role].label}</span>
                    <span className="block truncate text-[11.5px] text-muted">{ROLE_META[role].blurb}</span>
                  </span>
                  {active && <Check className="size-4 text-accent" />}
                </button>
              )
            })}

            {persona.role === 'worker' && team.length > 0 && (
              <div className="mt-1.5 border-t border-line pt-1.5">
                <p className="px-3 pb-1 pt-1 text-[10px] font-semibold uppercase tracking-wide text-faint">
                  Standing in for
                </p>
                <div className="max-h-44 overflow-y-auto">
                  {team.map((member) => {
                    const active = persona.identity === member
                    return (
                      <button
                        key={member}
                        role="menuitemradio"
                        aria-checked={active}
                        onClick={() => setIdentity(member)}
                        className={cn(
                          'flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left transition-colors',
                          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40',
                          active ? 'bg-accent-soft' : 'hover:bg-surface-2',
                        )}
                      >
                        <Avatar name={member} size="xs" />
                        <span className="flex-1 truncate text-[13px] font-medium text-ink">
                          {personLabel(member)}
                        </span>
                        {active && <Check className="size-3.5 text-accent" />}
                      </button>
                    )
                  })}
                </div>
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
