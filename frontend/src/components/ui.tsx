// Shared UI primitives. One definition each for buttons, cards, tags, avatars,
// status chips, and the loading/empty/error states — every screen composes
// these so spacing, radius, color, and motion stay consistent everywhere.

import { motion } from 'framer-motion'
import { Loader2, type LucideIcon } from 'lucide-react'
import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from 'react'
import { cn } from '../lib/cn'
import { avatarTone, initials, toneClasses, type Tone, type StatusView } from '../lib/format'

/* ---------------------------------------------------------------- Button */

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'soft'
type ButtonSize = 'sm' | 'md' | 'lg'

const BTN_VARIANT: Record<ButtonVariant, string> = {
  primary:
    'bg-accent text-accent-ink shadow-card-sm hover:bg-accent-hover active:scale-[.98]',
  secondary:
    'bg-surface text-ink border border-line hover:bg-surface-2 active:scale-[.98]',
  ghost: 'text-ink-soft hover:bg-surface-2 hover:text-ink',
  danger: 'bg-red text-white hover:brightness-95 active:scale-[.98]',
  soft: 'bg-accent-soft text-accent hover:brightness-[.97] active:scale-[.98]',
}
const BTN_SIZE: Record<ButtonSize, string> = {
  sm: 'h-8 px-3 text-[13px] gap-1.5 rounded-lg',
  md: 'h-10 px-4 text-sm gap-2 rounded-xl',
  lg: 'h-12 px-5 text-[15px] gap-2 rounded-xl',
}

export function Button({
  variant = 'secondary',
  size = 'md',
  icon: Icon,
  iconRight: IconRight,
  loading,
  className,
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant
  size?: ButtonSize
  icon?: LucideIcon
  iconRight?: LucideIcon
  loading?: boolean
}) {
  return (
    <button
      {...props}
      className={cn(
        'inline-flex items-center justify-center font-semibold transition-all duration-150',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40',
        'disabled:opacity-50 disabled:pointer-events-none whitespace-nowrap select-none',
        BTN_VARIANT[variant],
        BTN_SIZE[size],
        className,
      )}
      // Computed after the spread so a passed `disabled={false}` can't unlock a
      // button that is mid-request (loading).
      disabled={loading || props.disabled}
    >
      {loading ? (
        <Loader2 className="size-4 animate-spin" />
      ) : (
        Icon && <Icon className={cn(size === 'sm' ? 'size-3.5' : 'size-4')} />
      )}
      {children}
      {IconRight && !loading && <IconRight className={cn(size === 'sm' ? 'size-3.5' : 'size-4')} />}
    </button>
  )
}

export function IconButton({
  icon: Icon,
  className,
  label,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { icon: LucideIcon; label?: string }) {
  return (
    <button
      {...props}
      aria-label={label}
      title={label}
      className={cn(
        'inline-flex size-9 items-center justify-center rounded-lg text-ink-soft transition-colors',
        'hover:bg-surface-2 hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40',
        className,
      )}
    >
      <Icon className="size-[18px]" />
    </button>
  )
}

/* ------------------------------------------------------------------ Card */

export function Card({
  className,
  interactive,
  ...props
}: HTMLAttributes<HTMLDivElement> & { interactive?: boolean }) {
  return (
    <div
      className={cn(
        'rounded-2xl border border-line bg-surface shadow-card-sm',
        interactive && 'transition-shadow hover:shadow-card',
        className,
      )}
      {...props}
    />
  )
}

export function CardHeader({
  title,
  icon: Icon,
  count,
  action,
  className,
}: {
  title: ReactNode
  icon?: LucideIcon
  count?: ReactNode
  action?: ReactNode
  className?: string
}) {
  return (
    <div className={cn('flex items-center gap-2.5 px-5 pt-4 pb-3', className)}>
      {Icon && (
        <span className="flex size-7 items-center justify-center rounded-lg bg-accent-soft text-accent">
          <Icon className="size-4" />
        </span>
      )}
      <h2 className="text-[15px] font-bold tracking-tight text-ink">{title}</h2>
      {count != null && <span className="ml-auto text-xs font-medium text-faint">{count}</span>}
      {action && <span className={cn(count == null && 'ml-auto')}>{action}</span>}
    </div>
  )
}

/* ------------------------------------------------------------- Tag / Badge */

export function Tag({
  tone = 'muted',
  children,
  className,
  dot,
}: {
  tone?: Tone
  children: ReactNode
  className?: string
  dot?: boolean
}) {
  const c = toneClasses(tone)
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11px] font-bold',
        c.soft,
        className,
      )}
    >
      {dot && <span className={cn('size-1.5 rounded-full', c.dot)} />}
      {children}
    </span>
  )
}

export function StatusBadge({ status, className }: { status: StatusView; className?: string }) {
  return (
    <Tag tone={status.tone} className={className}>
      {status.label}
    </Tag>
  )
}

export function StatusDot({ tone, pulse, className }: { tone: Tone; pulse?: boolean; className?: string }) {
  const c = toneClasses(tone)
  return (
    <span className={cn('relative inline-flex size-2.5 rounded-full', c.dot, className)}>
      {pulse && <span className={cn('absolute inset-0 animate-ping rounded-full opacity-60', c.dot)} />}
    </span>
  )
}

/* ---------------------------------------------------------------- Avatar */

const AV_SIZE = { xs: 'size-6 text-[10px]', sm: 'size-7 text-[11px]', md: 'size-9 text-[13px]', lg: 'size-11 text-sm' }

export function Avatar({
  name,
  size = 'sm',
  className,
}: {
  name: unknown
  size?: keyof typeof AV_SIZE
  className?: string
}) {
  const c = toneClasses(avatarTone(name))
  return (
    <span
      className={cn(
        'inline-flex shrink-0 items-center justify-center rounded-full font-bold',
        c.soft,
        AV_SIZE[size],
        className,
      )}
      title={String(name ?? '')}
    >
      {initials(name)}
    </span>
  )
}

/* ------------------------------------------------------- loading / empty */

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cn('size-5 animate-spin text-accent', className)} />
}

export function Skeleton({ className }: { className?: string }) {
  return (
    <div className={cn('relative overflow-hidden rounded-lg bg-surface-2', className)}>
      <div className="absolute inset-0 -translate-x-full bg-gradient-to-r from-transparent via-black/[.04] to-transparent dark:via-white/[.05] [animation:shimmer_1.6s_infinite]" />
    </div>
  )
}

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  className,
}: {
  icon: LucideIcon
  title: string
  description?: ReactNode
  action?: ReactNode
  className?: string
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      className={cn('flex flex-col items-center justify-center px-6 py-12 text-center', className)}
    >
      <span className="mb-4 flex size-14 items-center justify-center rounded-2xl bg-accent-soft text-accent">
        <Icon className="size-7" />
      </span>
      <p className="text-[15px] font-bold text-ink">{title}</p>
      {description && <p className="mt-1.5 max-w-xs text-[13px] leading-relaxed text-muted">{description}</p>}
      {action && <div className="mt-5">{action}</div>}
    </motion.div>
  )
}

export function ErrorState({
  title = 'Something went wrong',
  description,
  onRetry,
  retrying,
  className,
}: {
  title?: string
  description?: ReactNode
  onRetry?: () => void
  retrying?: boolean
  className?: string
}) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center px-6 py-10 text-center',
        className,
      )}
    >
      <span className="mb-4 flex size-14 items-center justify-center rounded-2xl bg-red-soft text-red">
        <Loader2 className={cn('size-7', retrying && 'animate-spin')} />
      </span>
      <p className="text-[15px] font-bold text-ink">{title}</p>
      {description && <p className="mt-1.5 max-w-sm text-[13px] leading-relaxed text-muted">{description}</p>}
      {onRetry && (
        <Button variant="soft" size="sm" className="mt-5" onClick={onRetry} loading={retrying}>
          Try again
        </Button>
      )}
    </div>
  )
}

/* ----------------------------------------------------------------- Mono */

export function Mono({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={cn('font-mono text-[11px] text-faint tabular', className)}>{children}</span>
}
