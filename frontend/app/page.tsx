'use client'

import { Dashboard } from './components/Dashboard'
import { ErrorBoundary } from './components/ErrorBoundary'

export default function Home() {
  return (
    <main className="min-h-screen bg-background">
      <ErrorBoundary>
        <Dashboard />
      </ErrorBoundary>
    </main>
  )
}

