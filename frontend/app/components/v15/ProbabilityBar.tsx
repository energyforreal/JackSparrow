'use client'

import { cn } from '@/lib/utils'

interface ProbabilityBarProps {
  pBuy?: number
  pSell?: number
  pHold?: number
  className?: string
}

export function ProbabilityBar({ pBuy, pSell, pHold, className }: ProbabilityBarProps) {
  const b = typeof pBuy === 'number' ? pBuy : 0
  const s = typeof pSell === 'number' ? pSell : 0
  const h = typeof pHold === 'number' ? pHold : 0
  const sum = b + s + h || 1
  const wb = (b / sum) * 100
  const wh = (h / sum) * 100
  const ws = (s / sum) * 100
  return (
    <div className={cn('space-y-1', className)}>
      <p className="text-xs font-medium text-muted-foreground">Class probabilities</p>
      <div className="flex h-2 w-full overflow-hidden rounded-full bg-muted text-[0.65rem]">
        <div className="bg-emerald-600" style={{ width: `${wb}%` }} title={`buy ${b.toFixed(3)}`} />
        <div className="bg-muted-foreground/40" style={{ width: `${wh}%` }} title={`hold ${h.toFixed(3)}`} />
        <div className="bg-red-600" style={{ width: `${ws}%` }} title={`sell ${s.toFixed(3)}`} />
      </div>
      <div className="flex justify-between text-[0.65rem] text-muted-foreground">
        <span>B {b.toFixed(2)}</span>
        <span>H {h.toFixed(2)}</span>
        <span>S {s.toFixed(2)}</span>
      </div>
    </div>
  )
}
