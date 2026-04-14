'use client'

import { useState } from 'react'
import toast from 'react-hot-toast'
import { Button } from '@/components/ui/button'
import { getBackendProxyBase } from '@/lib/backendProxy'
import { Loader2, RotateCcw } from 'lucide-react'

type Phase = 'idle' | 'confirm' | 'loading' | 'done' | 'error'

interface ResetPaperTradesButtonProps {
  onSuccess: () => void
}

/**
 * Two-step confirm control that clears paper DB state via DELETE /api/v1/portfolio/reset.
 */
export function ResetPaperTradesButton({ onSuccess }: ResetPaperTradesButtonProps) {
  const [phase, setPhase] = useState<Phase>('idle')

  const runReset = async () => {
    setPhase('loading')
    try {
      const res = await fetch(`${getBackendProxyBase()}/api/v1/portfolio/reset`, {
        method: 'DELETE',
        headers: { Accept: 'application/json' },
      })
      if (res.status === 403) {
        toast.error('Reset is only available when paper trading mode is enabled on the server.')
        setPhase('error')
        return
      }
      if (!res.ok) {
        let detail = `Request failed (${res.status})`
        try {
          const body = (await res.json()) as { detail?: string }
          if (body?.detail) detail = body.detail
        } catch {
          // ignore
        }
        toast.error(detail)
        setPhase('error')
        return
      }
      onSuccess()
      setPhase('done')
      toast.success('Paper portfolio cleared')
      window.setTimeout(() => setPhase('idle'), 2000)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Reset failed')
      setPhase('error')
    }
  }

  const handleClick = () => {
    if (phase === 'idle') {
      setPhase('confirm')
      return
    }
    if (phase === 'confirm') {
      void runReset()
      return
    }
    if (phase === 'done' || phase === 'error') {
      setPhase('idle')
    }
  }

  const label =
    phase === 'idle'
      ? 'Reset paper trades'
      : phase === 'confirm'
        ? 'Click again to confirm'
        : phase === 'loading'
          ? 'Resetting…'
          : phase === 'done'
            ? 'Done'
            : 'Failed — tap to retry'

  return (
    <Button
      type="button"
      variant={phase === 'confirm' ? 'destructive' : 'outline'}
      size="sm"
      disabled={phase === 'loading'}
      onClick={handleClick}
      className="gap-1.5"
    >
      {phase === 'loading' ? (
        <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
      ) : (
        <RotateCcw className="h-3.5 w-3.5" aria-hidden />
      )}
      {label}
    </Button>
  )
}
