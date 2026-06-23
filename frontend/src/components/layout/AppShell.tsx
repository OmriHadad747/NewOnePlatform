// App frame. On large screens: a fixed left rail + sticky top strip. On small
// screens the rail collapses behind a hamburger (slide-in drawer), and the top
// strip keeps the global controls (theme, persona). Page content scrolls.

import { AnimatePresence, motion } from 'framer-motion'
import { Menu } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import { useProject } from '../../lib/queries'
import { IconButton } from '../ui'
import { Sidebar } from './Sidebar'
import { PersonaSwitcher } from './PersonaSwitcher'
import { ThemeToggle } from './ThemeToggle'
import { ProjectStatusPill } from './ProjectStatusPill'

export function AppShell() {
  const { data: project } = useProject()
  const name = project?.name
  const [navOpen, setNavOpen] = useState(false)
  const location = useLocation()
  const menuBtnRef = useRef<HTMLButtonElement>(null)
  const drawerRef = useRef<HTMLDivElement>(null)

  // Close the mobile drawer on route change (defensive — nav links also close it).
  useEffect(() => setNavOpen(false), [location.pathname])

  // Mobile drawer accessibility: lock scroll, Escape to close, move focus in on
  // open and restore it to the trigger on close (mirrors Modal/Drawer).
  useEffect(() => {
    if (!navOpen) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setNavOpen(false)
    document.addEventListener('keydown', onKey)
    document.body.style.overflow = 'hidden'
    drawerRef.current?.querySelector<HTMLElement>('a, button')?.focus()
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = ''
      menuBtnRef.current?.focus()
    }
  }, [navOpen])

  return (
    <div className="flex h-screen overflow-hidden bg-bg">
      <div className="hidden lg:flex">
        <Sidebar />
      </div>

      <AnimatePresence>
        {navOpen && (
          <div role="dialog" aria-modal="true" aria-label="Navigation" className="fixed inset-0 z-[70] lg:hidden">
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setNavOpen(false)}
              className="absolute inset-0 bg-black/40 backdrop-blur-sm"
            />
            <motion.div
              ref={drawerRef}
              initial={{ x: '-100%' }}
              animate={{ x: 0 }}
              exit={{ x: '-100%' }}
              transition={{ type: 'spring', stiffness: 360, damping: 36 }}
              className="absolute inset-y-0 left-0"
            >
              <Sidebar onNavigate={() => setNavOpen(false)} />
            </motion.div>
          </div>
        )}
      </AnimatePresence>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="z-20 flex h-16 shrink-0 items-center gap-3 border-b border-line bg-surface/80 px-4 backdrop-blur-md sm:px-6">
          <IconButton ref={menuBtnRef} icon={Menu} label="Open navigation" onClick={() => setNavOpen(true)} className="lg:hidden" />
          <div className="flex min-w-0 items-center gap-3">
            {name ? (
              <>
                <h1 className="truncate text-[15px] font-extrabold tracking-tight text-ink sm:text-[17px]">{name}</h1>
                <div className="hidden sm:block">
                  <ProjectStatusPill />
                </div>
              </>
            ) : (
              <span className="text-[15px] font-semibold text-muted">No project yet</span>
            )}
          </div>
          <div className="ml-auto flex items-center gap-2 sm:gap-3">
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
