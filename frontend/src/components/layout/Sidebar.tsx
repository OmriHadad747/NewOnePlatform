// Left rail: Shlomi's brand mark + role-aware navigation. The nav adapts to
// the active persona so each hat sees only what's relevant, while the layout,
// icons, and active-state styling stay identical across roles.

import {
  CheckSquare,
  LayoutGrid,
  ListChecks,
  type LucideIcon,
  MessagesSquare,
  MonitorPlay,
  Sparkles,
  Inbox,
} from 'lucide-react'
import { NavLink } from 'react-router-dom'
import { cn } from '../../lib/cn'
import { AGENT_NAME, usePersona, type Role } from '../../lib/persona'
import { useProposals } from '../../lib/queries'

interface NavItem {
  to: string
  label: string
  icon: LucideIcon
  badge?: number
}

const NAV_BY_ROLE: Record<Role, (badges: { proposals: number }) => NavItem[]> = {
  worker: () => [
    { to: '/worker', label: 'My work', icon: CheckSquare },
    { to: '/board', label: 'Tasks & risks', icon: LayoutGrid },
    { to: '/timeline', label: 'Timeline', icon: ListChecks },
  ],
  manager: ({ proposals }) => [
    { to: '/manager', label: 'Approvals', icon: Inbox, badge: proposals },
    { to: '/board', label: 'Tasks & risks', icon: LayoutGrid },
    { to: '/timeline', label: 'Timeline', icon: ListChecks },
    { to: '/threads', label: 'Threads', icon: MessagesSquare },
  ],
  exec: () => [
    { to: '/exec', label: 'Overview', icon: LayoutGrid },
    { to: '/board', label: 'Tasks & risks', icon: LayoutGrid },
    { to: '/timeline', label: 'Timeline', icon: ListChecks },
  ],
  demo: ({ proposals }) => [
    { to: '/demo', label: 'Demo console', icon: MonitorPlay },
    { to: '/manager', label: 'Approvals', icon: Inbox, badge: proposals },
    { to: '/board', label: 'Tasks & risks', icon: LayoutGrid },
    { to: '/timeline', label: 'Timeline', icon: ListChecks },
  ],
}

export function Sidebar() {
  const { persona } = usePersona()
  const { data: proposals } = useProposals({ poll: true })
  const items = NAV_BY_ROLE[persona.role]({ proposals: proposals?.length ?? 0 })

  return (
    <aside className="flex h-full w-[244px] shrink-0 flex-col gap-1 border-r border-line bg-surface px-3 py-5">
      <div className="flex items-center gap-3 px-2 pb-5">
        <span className="flex size-9 items-center justify-center rounded-xl bg-gradient-to-br from-accent to-[#e2a24d] text-accent-ink shadow-card-sm">
          <Sparkles className="size-5" />
        </span>
        <div className="leading-tight">
          <p className="text-[15px] font-extrabold tracking-tight text-ink">{AGENT_NAME}</p>
          <p className="text-[11px] font-medium text-muted">AI project manager</p>
        </div>
      </div>

      <nav className="flex flex-col gap-0.5">
        {items.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              cn(
                'group flex items-center gap-3 rounded-xl px-3 py-2.5 text-[13.5px] font-semibold transition-colors',
                isActive ? 'bg-accent-soft text-accent' : 'text-ink-soft hover:bg-surface-2 hover:text-ink',
              )
            }
          >
            <item.icon className="size-[18px]" />
            <span className="flex-1">{item.label}</span>
            {item.badge ? (
              <span className="flex h-5 min-w-5 items-center justify-center rounded-full bg-accent px-1.5 text-[11px] font-bold text-accent-ink">
                {item.badge}
              </span>
            ) : null}
          </NavLink>
        ))}
      </nav>

      <div className="mt-auto rounded-2xl border border-line bg-surface-2 p-3">
        <div className="flex items-center gap-2.5">
          <span className="relative flex size-8 items-center justify-center rounded-lg bg-accent-soft text-accent">
            <Sparkles className="size-4" />
            <span className="absolute -right-0.5 -top-0.5 size-2.5 rounded-full border-2 border-surface-2 bg-green" />
          </span>
          <div className="leading-tight">
            <p className="text-[12.5px] font-bold text-ink">{AGENT_NAME} is watching</p>
            <p className="text-[11px] text-muted">Reconciling project state</p>
          </div>
        </div>
      </div>
    </aside>
  )
}
