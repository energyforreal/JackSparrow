'use client'

import Image from 'next/image'

import { Badge } from '@/components/ui/badge'
import { SystemClock } from './SystemClock'
import { cn } from '@/lib/utils'
import { Wifi, WifiOff } from 'lucide-react'
import { ResetPaperTradesButton } from './ResetPaperTradesButton'

interface HeaderProps {
  isConnected?: boolean
  onPaperPortfolioReset?: () => void
}

export function Header({ isConnected = false, onPaperPortfolioReset }: HeaderProps) {
  return (
    <header className="border-b bg-card">
      <div className="container mx-auto flex flex-col gap-4 px-4 py-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <Image
            src="/logo.png"
            alt="JackSparrow Trading Agent logo"
            width={64}
            height={64}
            priority
            className="h-12 w-12"
          />
          <div className="hidden flex-col leading-tight sm:flex">
            <span className="text-lg font-semibold tracking-tight text-foreground">
              JackSparrow
            </span>
            <span className="text-xs uppercase text-muted-foreground tracking-[0.2em]">
              Trading Agent
            </span>
          </div>
        </div>
        <div className="flex w-full flex-col gap-3 sm:w-auto sm:items-end">
          {onPaperPortfolioReset ? (
            <div className="flex w-full justify-end">
              <ResetPaperTradesButton onSuccess={onPaperPortfolioReset} />
            </div>
          ) : null}
          <SystemClock className="w-full sm:w-auto" />
          <Badge
            variant={isConnected ? 'default' : 'destructive'}
            className={cn(
              'flex items-center gap-2 self-start text-xs sm:self-end',
              isConnected && 'bg-success text-white hover:bg-success/90',
              !isConnected && 'bg-error text-white hover:bg-error/90'
            )}
          >
            {isConnected ? (
              <>
                <Wifi className="h-3 w-3" />
                Connected
              </>
            ) : (
              <>
                <WifiOff className="h-3 w-3" />
                Disconnected
              </>
            )}
          </Badge>
        </div>
      </div>
    </header>
  )
}

