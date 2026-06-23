import { Moon, Sun } from 'lucide-react'
import { motion } from 'framer-motion'
import { useTheme } from '../../lib/theme'

export function ThemeToggle() {
  const { theme, toggle } = useTheme()
  const dark = theme === 'dark'
  return (
    <button
      onClick={toggle}
      aria-label={dark ? 'Switch to light mode' : 'Switch to dark mode'}
      className="relative flex h-9 w-16 items-center rounded-full border border-line bg-surface-2 px-1 transition-colors"
    >
      <motion.span
        layout
        transition={{ type: 'spring', stiffness: 500, damping: 34 }}
        className="flex size-7 items-center justify-center rounded-full bg-surface shadow-card-sm"
        style={{ marginLeft: dark ? 'auto' : 0 }}
      >
        {dark ? <Moon className="size-4 text-accent" /> : <Sun className="size-4 text-accent" />}
      </motion.span>
    </button>
  )
}
