'use client'

import { AlertTriangle } from 'lucide-react'
import { cn } from '@/lib/utils'

interface PaperTradingBannerProps {
  isPaperTrading: boolean
  className?: string
}

export function PaperTradingBanner({ isPaperTrading, className }: PaperTradingBannerProps) {
  if (!isPaperTrading) return null

  return (
    <div
      className={cn(
        'w-full bg-amber-50 dark:bg-amber-950/20 border-b-2 border-amber-400 dark:border-amber-600',
        'px-4 py-3 flex items-center gap-3',
        className
      )}
      role="alert"
      aria-live="polite"
      aria-label="Paper Trading Mode Warning"
    >
      <AlertTriangle className="h-5 w-5 text-amber-600 dark:text-amber-400 flex-shrink-0" />
      <div className="flex-1">
        <p className="text-sm font-semibold text-amber-900 dark:text-amber-100">
          Paper Trading Mode Active
        </p>
        <p className="text-xs text-amber-700 dark:text-amber-300 mt-0.5">
          All trades are simulated. No real money is being used.
        </p>
      </div>
    </div>
  )
}
