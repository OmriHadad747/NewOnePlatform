// Top-level safety net. A render-time crash anywhere shows a calm, on-brand
// recovery screen instead of a white page — in keeping with the platform's
// "resilient, never scary" stance.

import { Component, type ErrorInfo, type ReactNode } from 'react'
import { RotateCcw } from 'lucide-react'

interface Props {
  children: ReactNode
}
interface State {
  error: Error | null
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // eslint-disable-next-line no-console
    console.error('Unhandled UI error:', error, info.componentStack)
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-5 bg-bg px-6 text-center">
        <span className="flex size-16 items-center justify-center rounded-2xl bg-red-soft text-red">
          <RotateCcw className="size-8" />
        </span>
        <div>
          <h1 className="text-xl font-extrabold text-ink">Something tripped up</h1>
          <p className="mt-1.5 max-w-sm text-sm text-muted">
            Shlomi hit an unexpected snag rendering this screen. Reloading usually clears it.
          </p>
        </div>
        <button
          onClick={() => window.location.reload()}
          className="inline-flex h-10 items-center gap-2 rounded-xl bg-accent px-5 text-sm font-semibold text-accent-ink shadow-card-sm transition-colors hover:bg-accent-hover"
        >
          <RotateCcw className="size-4" /> Reload
        </button>
      </div>
    )
  }
}
