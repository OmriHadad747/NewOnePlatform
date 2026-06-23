// App frame: fixed left rail + a sticky top strip carrying global context
// (project name + health) and the global controls (persona switcher, theme).
// Page content renders through <Outlet/> and scrolls independently.

import { Outlet } from 'react-router-dom'
import { useProject } from '../../lib/queries'
import { Sidebar } from './Sidebar'
import { PersonaSwitcher } from './PersonaSwitcher'
import { ThemeToggle } from './ThemeToggle'
import { ProjectStatusPill } from './ProjectStatusPill'

export function AppShell() {
  const { data: project } = useProject()
  const name = project?.name

  return (
    <div className="flex h-screen overflow-hidden bg-bg">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="z-20 flex h-16 shrink-0 items-center gap-4 border-b border-line bg-surface/80 px-6 backdrop-blur-md">
          <div className="flex min-w-0 items-center gap-3">
            {name ? (
              <>
                <h1 className="truncate text-[17px] font-extrabold tracking-tight text-ink">{name}</h1>
                <ProjectStatusPill />
              </>
            ) : (
              <span className="text-[15px] font-semibold text-muted">No project yet</span>
            )}
          </div>
          <div className="ml-auto flex items-center gap-3">
            <ThemeToggle />
            <PersonaSwitcher />
          </div>
        </header>
        <main className="min-h-0 flex-1 overflow-y-auto bg-grain">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
