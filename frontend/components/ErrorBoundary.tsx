'use client';

/**
 * Every failure path in the original frontend was `console.error` — a failed
 * fetch was visually indistinguishable from zero results (page.tsx:54,85;
 * EvidencePanel.tsx:35), and an uncaught render error crashed to a blank
 * white screen with nothing in the UI explaining why. This is the last-resort
 * boundary for the latter; the API client and hooks handle the former with a
 * visible banner instead of silence.
 */

import { Component, type ErrorInfo, type ReactNode } from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // eslint-disable-next-line no-console
    console.error('TRINETRA UI crashed:', error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="flex min-h-screen items-center justify-center bg-command-bg p-6">
          <div className="max-w-md rounded-lg border border-red-500/30 bg-command-card p-6 text-center">
            <AlertTriangle className="mx-auto mb-3 h-10 w-10 text-red-400" />
            <h1 className="mb-2 text-lg font-semibold text-command-textBright">
              Something went wrong
            </h1>
            <p className="mb-4 text-sm text-command-textMuted">
              {this.state.error.message || 'An unexpected error occurred in the analyst workspace.'}
            </p>
            <button
              onClick={() => this.setState({ error: null })}
              className="inline-flex items-center gap-2 rounded-md bg-command-accent/20 px-4 py-2 text-sm font-medium text-command-accent hover:bg-command-accent/30"
            >
              <RefreshCw className="h-4 w-4" />
              Try again
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
