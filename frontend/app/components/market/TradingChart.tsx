'use client'

import { useEffect, useRef } from 'react'
import {
  CandlestickSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  HistogramSeries,
  LineStyle,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type Time,
} from 'lightweight-charts'
import type { MarketChartResponse } from '@/types'
import { mapChartPayloadToView, type ChartPriceLineView } from '@/utils/chartAdapter'
import { ZoneBandsPrimitive } from './zonePrimitive'

interface TradingChartProps {
  data: MarketChartResponse
  livePrice?: number | null
  className?: string
}

const PRICE_LINE_STYLE: Record<
  ChartPriceLineView['lineStyle'],
  LineStyle
> = {
  solid: LineStyle.Solid,
  dashed: LineStyle.Dashed,
}

/**
 * Interactive candlestick chart with algorithmic trade levels overlaid.
 */
export function TradingChart({ data, livePrice, className }: TradingChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const candleRef = useRef<ISeriesApi<'Candlestick', Time> | null>(null)
  const volumeRef = useRef<ISeriesApi<'Histogram', Time> | null>(null)
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null)
  const zonesRef = useRef<ZoneBandsPrimitive | null>(null)
  const priceLinesRef = useRef<Map<string, IPriceLine>>(new Map())
  const lastSeriesKey = useRef<string>('')

  useEffect(() => {
    const el = containerRef.current
    if (!el) return

    const chart = createChart(el, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: '#64748b',
        fontSize: 12,
      },
      grid: {
        vertLines: { color: 'rgba(148, 163, 184, 0.25)' },
        horzLines: { color: 'rgba(148, 163, 184, 0.25)' },
      },
      rightPriceScale: {
        borderVisible: false,
      },
      timeScale: {
        borderVisible: false,
        timeVisible: true,
        secondsVisible: false,
      },
      crosshair: {
        mode: 1,
      },
    })

    const candles = chart.addSeries(CandlestickSeries, {
      upColor: '#16a34a',
      downColor: '#dc2626',
      borderUpColor: '#16a34a',
      borderDownColor: '#dc2626',
      wickUpColor: '#16a34a',
      wickDownColor: '#dc2626',
    })
    candles.priceScale().applyOptions({
      scaleMargins: { top: 0.08, bottom: 0.22 },
    })

    const volume = chart.addSeries(HistogramSeries, {
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
    })
    chart.priceScale('volume').applyOptions({
      scaleMargins: { top: 0.82, bottom: 0 },
    })

    const zones = new ZoneBandsPrimitive()
    candles.attachPrimitive(zones)
    const markers = createSeriesMarkers(candles, [])

    chartRef.current = chart
    candleRef.current = candles
    volumeRef.current = volume
    zonesRef.current = zones
    markersRef.current = markers

    const onResize = () => {
      // autoSize handles most cases; force a sync on container changes
      chart.timeScale().fitContent()
    }
    window.addEventListener('resize', onResize)

    return () => {
      window.removeEventListener('resize', onResize)
      priceLinesRef.current.clear()
      chart.remove()
      chartRef.current = null
      candleRef.current = null
      volumeRef.current = null
      zonesRef.current = null
      markersRef.current = null
      lastSeriesKey.current = ''
    }
  }, [])

  useEffect(() => {
    const candles = candleRef.current
    const volume = volumeRef.current
    const zones = zonesRef.current
    const markersApi = markersRef.current
    if (!candles || !volume || !zones || !markersApi) return

    const view = mapChartPayloadToView(data, livePrice)
    const seriesKey = `${data.timeframe}:${data.candles.length}:${data.candles[0]?.time ?? 0}:${data.candles[data.candles.length - 1]?.time ?? 0}`

    if (seriesKey !== lastSeriesKey.current) {
      candles.setData(
        view.candles.map((c) => ({
          time: c.time as Time,
          open: c.open,
          high: c.high,
          low: c.low,
          close: c.close,
        }))
      )
      volume.setData(
        view.volume.map((v, index) => {
          const candle = view.candles[index]
          const up = candle ? candle.close >= candle.open : true
          return {
            time: v.time as Time,
            value: v.value,
            color: up ? 'rgba(22, 163, 74, 0.35)' : 'rgba(220, 38, 38, 0.35)',
          }
        })
      )
      chartRef.current?.timeScale().fitContent()
      lastSeriesKey.current = seriesKey
    }

    zones.setZones(view.zones)
    markersApi.setMarkers(
      view.markers.map((m) => ({
        time: m.time as Time,
        position: m.position,
        color: m.color,
        shape: m.shape as 'arrowUp' | 'arrowDown' | 'circle' | 'square',
        text: m.text,
      }))
    )

    const existing = priceLinesRef.current
    const nextKinds = new Set(view.priceLines.map((line) => line.kind))
    for (const [kind, line] of existing.entries()) {
      if (!nextKinds.has(kind as ChartPriceLineView['kind'])) {
        candles.removePriceLine(line)
        existing.delete(kind)
      }
    }
    for (const lineView of view.priceLines) {
      const current = existing.get(lineView.kind)
      const options = {
        price: lineView.price,
        color: lineView.color,
        lineWidth: 2 as const,
        lineStyle: PRICE_LINE_STYLE[lineView.lineStyle],
        axisLabelVisible: true,
        title: lineView.title,
      }
      if (current) {
        current.applyOptions(options)
      } else {
        existing.set(lineView.kind, candles.createPriceLine(options))
      }
    }
  }, [data, livePrice])

  return (
    <div
      ref={containerRef}
      className={className ?? 'h-[480px] w-full rounded-md border border-border bg-card'}
      data-testid="trading-chart"
    />
  )
}
