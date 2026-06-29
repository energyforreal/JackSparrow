'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'

export interface MarketStateSnapshot {
  trend?: string
  trend_strength?: string
  trend_age_candles?: number
  momentum?: string
  breakout_status?: string
  retest_status?: string
  structure?: string
  liquidity?: string
  volatility?: string
  regime?: string
  confidence?: string
  direction_bias?: string
  mtf?: Record<string, string>
}

interface MarketStateCardProps {
  marketState?: MarketStateSnapshot | null
  fsmState?: string | null
  positionLifecycle?: string | null
}

function Row({ label, value }: { label: string; value?: string | number | null }) {
  if (value == null || value === '') return null
  return (
    <div className="flex justify-between gap-2 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium capitalize">{String(value)}</span>
    </div>
  )
}

export function MarketStateCard({ marketState, fsmState, positionLifecycle }: MarketStateCardProps) {
  if (!marketState && !fsmState) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Market State</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">Waiting for rule-based market snapshot…</p>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader className="pb-2 flex flex-row items-center justify-between">
        <CardTitle className="text-base">Market State</CardTitle>
        <div className="flex gap-1 flex-wrap justify-end">
          {fsmState && <Badge variant="outline">{fsmState}</Badge>}
          {positionLifecycle && <Badge variant="secondary">{positionLifecycle}</Badge>}
        </div>
      </CardHeader>
      <CardContent className="space-y-1">
        <Row label="Trend" value={marketState?.trend} />
        <Row label="Strength" value={marketState?.trend_strength} />
        <Row label="Age (bars)" value={marketState?.trend_age_candles} />
        <Row label="Momentum" value={marketState?.momentum} />
        <Row label="Breakout" value={marketState?.breakout_status} />
        <Row label="Retest" value={marketState?.retest_status} />
        <Row label="Structure" value={marketState?.structure} />
        <Row label="Liquidity" value={marketState?.liquidity} />
        <Row label="Volatility" value={marketState?.volatility} />
        <Row label="Confidence" value={marketState?.confidence} />
        <Row label="Bias" value={marketState?.direction_bias} />
      </CardContent>
    </Card>
  )
}
