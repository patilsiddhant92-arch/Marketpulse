import { Component, type ErrorInfo, type ReactNode } from 'react';
import { ErrorState } from './ErrorState';

export interface ErrorBoundaryProps {
  /** Shown in the fallback, e.g. "Desk". */
  name: string;
  children: ReactNode;
  /** Changing any of these resets the boundary (e.g. [pathname, as_of]). */
  resetKeys?: readonly unknown[];
  fallback?: (error: unknown, reset: () => void) => ReactNode;
}

interface State {
  error: unknown;
  keys: readonly unknown[] | undefined;
}

/** One per tab so a crash in one tab never blanks the shell. */
export class ErrorBoundary extends Component<ErrorBoundaryProps, State> {
  state: State = { error: null, keys: this.props.resetKeys };

  static getDerivedStateFromError(error: unknown): Partial<State> {
    return { error: error ?? new Error('Unknown error') };
  }

  static getDerivedStateFromProps(props: ErrorBoundaryProps, state: State): Partial<State> | null {
    const a = props.resetKeys ?? [];
    const b = state.keys ?? [];
    const changed = a.length !== b.length || a.some((k, i) => !Object.is(k, b[i]));
    if (changed) return { keys: props.resetKeys, error: null };
    return null;
  }

  componentDidCatch(error: unknown, info: ErrorInfo) {
    console.error(`[${this.props.name}] crashed`, error, info.componentStack);
  }

  reset = () => this.setState({ error: null });

  render() {
    if (this.state.error) {
      if (this.props.fallback) return this.props.fallback(this.state.error, this.reset);
      return <ErrorState error={this.state.error} title={`${this.props.name} crashed`} onRetry={this.reset} className="h-full" />;
    }
    return this.props.children;
  }
}
