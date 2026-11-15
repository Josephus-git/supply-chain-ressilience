import { AlertTriangle } from 'lucide-react'
import { Component, type ReactNode } from 'react'

/** Contains a render error to one region instead of blanking the whole app. */
export class ErrorBoundary extends Component<{ children: ReactNode; label?: string }, { error: Error | null }> {
  state = { error: null as Error | null }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <div className="flex h-full min-h-32 flex-col items-center justify-center gap-2 p-6 text-center text-sm text-muted-foreground">
        <AlertTriangle className="size-5 text-destructive" />
        <div>{this.props.label ?? 'This section'} failed to render.</div>
        <code className="max-w-lg text-xs break-words">{this.state.error.message}</code>
        <button className="text-xs underline underline-offset-2" onClick={() => this.setState({ error: null })}>Try again</button>
      </div>
    )
  }
}
