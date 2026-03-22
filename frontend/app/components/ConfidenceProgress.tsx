'use client'

import * as React from "react"
import * as ProgressPrimitive from "@radix-ui/react-progress"
import { cn } from '@/lib/utils'
import { normalizeConfidenceToPercent, getConfidenceColorClass } from '@/utils/formatters'

interface ConfidenceProgressProps {
  value: number | null | undefined
  className?: string
  variant?: 'confidence' | 'health' | 'reasoningStep'
}

/** 80% / 60% tiers for reasoning-chain step bars (0–100 scale after normalization). */
function getReasoningStepColorClass(percent: number): string {
  if (percent >= 80) return 'bg-green-500'
  if (percent >= 60) return 'bg-yellow-500'
  return 'bg-red-500'
}

function getHealthColorClass(score: number): string {
  if (score >= 90) {
    return 'bg-green-500'
  } else if (score >= 70) {
    return 'bg-amber-500'
  } else if (score >= 50) {
    return 'bg-yellow-500'
  } else {
    return 'bg-red-500'
  }
}

export function ConfidenceProgress({ value, className, variant = 'confidence' }: ConfidenceProgressProps) {
  const percent = normalizeConfidenceToPercent(value)
  const colorClass =
    variant === 'health'
      ? getHealthColorClass(percent)
      : variant === 'reasoningStep'
        ? getReasoningStepColorClass(percent)
        : getConfidenceColorClass(value ?? 0)

  return (
    <ProgressPrimitive.Root
      className={cn(
        "relative h-4 w-full overflow-hidden rounded-full bg-secondary",
        className
      )}
      value={percent}
    >
      <ProgressPrimitive.Indicator
        className={cn(
          "h-full w-full flex-1 transition-all",
          colorClass
        )}
        style={{ transform: `translateX(-${100 - percent}%)` }}
      />
    </ProgressPrimitive.Root>
  )
}
