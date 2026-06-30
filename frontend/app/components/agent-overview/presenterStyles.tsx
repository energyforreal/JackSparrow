'use client'

import type { ColorToken } from '@/utils/agent-overview/agentOverviewPresenter'
import { Check, Minus, X } from 'lucide-react'
import { cn } from '@/lib/utils'

export function colorTokenClasses(token: ColorToken): string {
  switch (token) {
    case 'success':
      return 'text-green-600 dark:text-green-400'
    case 'warning':
      return 'text-amber-600 dark:text-amber-400'
    case 'error':
      return 'text-red-600 dark:text-red-400'
    case 'info':
      return 'text-blue-600 dark:text-blue-400'
    default:
      return 'text-muted-foreground'
  }
}

export function colorTokenBg(token: ColorToken): string {
  switch (token) {
    case 'success':
      return 'bg-green-500/10 border-green-500/30'
    case 'warning':
      return 'bg-amber-500/10 border-amber-500/30'
    case 'error':
      return 'bg-red-500/10 border-red-500/30'
    case 'info':
      return 'bg-blue-500/10 border-blue-500/30'
    default:
      return 'bg-muted/30 border-border/60'
  }
}

export function StatusIcon({
  kind,
  className,
}: {
  kind: 'check' | 'x' | 'minus'
  className?: string
}) {
  const base = cn('h-4 w-4 shrink-0', className)
  if (kind === 'check') {
    return <Check className={cn(base, 'text-green-600 dark:text-green-400')} aria-hidden />
  }
  if (kind === 'x') {
    return <X className={cn(base, 'text-red-600 dark:text-red-400')} aria-hidden />
  }
  return <Minus className={cn(base, 'text-muted-foreground')} aria-hidden />
}
