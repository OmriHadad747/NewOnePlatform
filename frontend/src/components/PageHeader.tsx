import type { ReactNode } from 'react'
import { cn } from '../lib/cn'

// Consistent page title block — same type scale, spacing, and action slot on
// every screen, so switching roles never shifts the layout grammar.
export function PageHeader({
  eyebrow,
  title,
  subtitle,
  actions,
  className,
}: {
  eyebrow?: ReactNode
  title: ReactNode
  subtitle?: ReactNode
  actions?: ReactNode
  className?: string
}) {
  return (
    <div className={cn('mb-6 flex flex-wrap items-start gap-4', className)}>
      <div className="min-w-0 flex-1">
        {eyebrow && (
          <p className="mb-1 text-[12px] font-bold uppercase tracking-wide text-accent">{eyebrow}</p>
        )}
        <h1 className="text-[26px] font-extrabold leading-tight tracking-tight text-ink">{title}</h1>
        {subtitle && <p className="mt-1.5 max-w-2xl text-[14px] leading-relaxed text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2.5">{actions}</div>}
    </div>
  )
}

export function PageContainer({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn('mx-auto w-full max-w-6xl px-6 py-7 sm:px-8', className)}>{children}</div>
}
