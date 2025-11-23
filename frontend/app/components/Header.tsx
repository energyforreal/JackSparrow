'use client'

import { Badge } from '@/components/ui/badge'
import { SystemClock } from './SystemClock'
import { cn } from '@/lib/utils'
import { Wifi, WifiOff } from 'lucide-react'

interface HeaderProps {
  isConnected?: boolean
}

export function Header({ isConnected = false }: HeaderProps) {
  return (
    <header className="border-b bg-card">
      <div className="container mx-auto flex items-center justify-between px-4 py-4">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-bold text-foreground">
            JackSparrow Trading Agent
          </h1>
        </div>
        <div className="flex items-center gap-4">
          <SystemClock />
          <Badge
            variant={isConnected ? 'default' : 'destructive'}
            className={cn(
              'flex items-center gap-2',
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

