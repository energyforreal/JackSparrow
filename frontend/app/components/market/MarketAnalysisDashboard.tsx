'use client'

import { RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { useChartData } from '@/hooks/useChartData'
import type { MarketData } from '@/hooks/useTradingData'
import type {
  ChartPatternMarker,
  ChartTimeframe,
  Signal,
  StructureZone,
} from '@/types'
import {
  CHART_TIMEFRAMES,
  timeframeLabel,
} from '@/utils/chartAdapter'
import { TradingChart } from './TradingChart'
import { useState } from 'react'

interface MarketAnalysisDashboardProps {
  signal: Signal | null
  marketTick?: MarketData | null
  symbol?: string
}

function formatPrice(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—'
  return value.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
}

function formatScore(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—'
  return `${value.toFixed(0)}/100`
}

function formatRr(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—'
  return `${value.toFixed(2)}`
}

function primaryZone(zones: StructureZone[] | undefined): StructureZone | null {
  if (!zones || zones.length === 0) return null
  const preferred = zones.find((z) => z.timeframe === '1h')
  return preferred ?? zones[0]
}

function signalBadgeClass(signal: string): string {
  const upper = signal.toUpperCase()
  if (upper.includes('BUY')) return 'bg-emerald-600 text-white hover:bg-emerald-600'
  if (upper.includes('SELL')) return 'bg-red-600 text-white hover:bg-red-600'
  return 'bg-muted text-muted-foreground'
}

/**
 * Market Analysis tab: candlestick chart, timeframe picker, and trade panel.
 */
export function MarketAnalysisDashboard({
  signal,
  marketTick,
  symbol = 'BTCUSD',
}: MarketAnalysisDashboardProps) {
  const [timeframe, setTimeframe] = useState<ChartTimeframe>('15m')
  const { data, livePrice, isLoading, error, refetch } = useChartData({
    symbol,
    timeframe,
    signal,
    marketTick,
  })

  const plan = data?.trade_plan
  const support = primaryZone(data?.support_zones)
  const resistance = primaryZone(data?.resistance_zones)
  const displayPrice = livePrice ?? data?.current_price ?? null
  const patterns = [...(data?.active_patterns || [])]
    .sort((a, b) => b.time - a.time)
    .slice(0, 8)

  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
          <div>
            <CardTitle className="text-base">Market Analysis</CardTitle>
            <p className="text-xs text-muted-foreground mt-1">
              Levels from JackSparrow&apos;s last closed-candle decision
            </p>
          </div>
          <div className="flex items-center gap-2">
            <div className="flex rounded-md border border-border p-0.5">
              {CHART_TIMEFRAMES.map((tf) => (
                <Button
                  key={tf}
                  type="button"
                  size="sm"
                  variant={timeframe === tf ? 'default' : 'ghost'}
                  className="h-7 px-2 text-xs"
                  onClick={() => setTimeframe(tf)}
                >
                  {timeframeLabel(tf)}
                </Button>
              ))}
            </div>
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="h-7 w-7 p-0"
              onClick={() => void refetch()}
              aria-label="Refresh chart"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${isLoading ? 'animate-spin' : ''}`} />
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {error && (
            <p className="mb-3 text-sm text-destructive">{error}</p>
          )}
          {data ? (
            <TradingChart data={data} livePrice={livePrice} />
          ) : (
            <div className="flex h-[480px] items-center justify-center rounded-md border border-dashed border-border text-sm text-muted-foreground">
              {isLoading ? 'Loading chart…' : 'No candle data'}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Trade Plan</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <Row label="Instrument" value={`${symbol} Perpetual`} />
          <div className="flex items-center justify-between gap-2">
            <span className="text-muted-foreground">Signal</span>
            <Badge className={signalBadgeClass(plan?.signal || 'HOLD')}>
              {plan?.signal || 'HOLD'}
            </Badge>
          </div>
          <Row label="Algorithmic score" value={formatScore(plan?.score)} />
          <Row label="Current price" value={formatPrice(displayPrice)} />
          <Row
            label="Support"
            value={
              support
                ? `${formatPrice(support.price)} (${support.timeframe})`
                : '—'
            }
          />
          <Row
            label="Resistance"
            value={
              resistance
                ? `${formatPrice(resistance.price)} (${resistance.timeframe})`
                : '—'
            }
          />
          <Row label="Expected entry" value={formatPrice(plan?.entry)} />
          <Row label="Stop loss" value={formatPrice(plan?.stop_loss)} />
          <Row label="Take profit" value={formatPrice(plan?.take_profit)} />
          <Row label="Risk/reward" value={formatRr(plan?.risk_reward)} />
          <div className="flex items-center justify-between gap-2">
            <span className="text-muted-foreground">Signal validity</span>
            <Badge variant={plan?.valid ? 'default' : 'secondary'}>
              {plan?.valid ? 'Valid' : 'Invalid'}
            </Badge>
          </div>
          <div className="space-y-2 border-t border-border pt-3">
            <p className="text-xs font-medium text-foreground">Active patterns</p>
            {patterns.length === 0 ? (
              <p className="text-xs text-muted-foreground">No recent hits</p>
            ) : (
              <ul className="space-y-1.5">
                {patterns.map((pattern) => (
                  <PatternRow key={`${pattern.time}-${pattern.name}`} pattern={pattern} />
                ))}
              </ul>
            )}
          </div>
          {plan?.candle_timestamp && (
            <p className="pt-2 text-xs text-muted-foreground">
              Decision candle: {plan.candle_timestamp}
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function PatternRow({ pattern }: { pattern: ChartPatternMarker }) {
  const bullish = String(pattern.direction).toLowerCase() === 'bullish'
  const kindLabel = String(pattern.kind).toLowerCase() === 'chart' ? 'Chart' : 'Candle'
  return (
    <li className="flex items-start justify-between gap-2 text-xs">
      <div className="min-w-0">
        <p className="truncate font-medium text-foreground">{pattern.label}</p>
        <p className="text-muted-foreground">
          {kindLabel} · {pattern.timeframe || '—'}
        </p>
      </div>
      <Badge
        variant="outline"
        className={
          bullish
            ? 'border-emerald-600/40 text-emerald-700 dark:text-emerald-400'
            : 'border-red-600/40 text-red-700 dark:text-red-400'
        }
      >
        {bullish ? 'Bull' : 'Bear'}
      </Badge>
    </li>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium tabular-nums text-foreground text-right">{value}</span>
    </div>
  )
}
