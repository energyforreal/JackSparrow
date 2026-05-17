'use client'

import Image from 'next/image'

import { Badge } from '@/components/ui/badge'
import { SystemClock } from './SystemClock'
import { cn } from '@/lib/utils'
import { useTestnetContext } from '@/hooks/useTestnetContext'
import type { HealthStatus } from '@/types'
import { Wifi, WifiOff } from 'lucide-react'

interface HeaderProps {
  isConnected?: boolean
  health?: HealthStatus | null
}

export function Header({ isConnected = false, health }: HeaderProps) {
  const { isTestnet, testnetConnected } = useTestnetContext(health)
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
          <SystemClock className="w-full sm:w-auto" />
          <div className="flex flex-wrap items-center gap-2 self-start sm:self-end">
            {isTestnet && (
              <Badge
                variant="outline"
                className={
                  testnetConnected
                    ? 'border-amber-500/60 bg-amber-500/10 text-amber-700 dark:text-amber-300 text-xs'
                    : 'border-destructive/60 bg-destructive/10 text-destructive text-xs'
                }
              >
                {testnetConnected ? 'Delta Testnet' : 'Testnet Offline'}
              </Badge>
            )}
            <Badge
              variant={isConnected ? 'default' : 'destructive'}
              className={cn(
                'flex items-center gap-2 text-xs',
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
      </div>
    </header>
  )
}
