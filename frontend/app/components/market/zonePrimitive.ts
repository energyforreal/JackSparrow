/**
 * Horizontal band primitive for support/resistance zones on Lightweight Charts.
 */

import type {
  IChartApi,
  ISeriesApi,
  ISeriesPrimitive,
  IPrimitivePaneRenderer,
  IPrimitivePaneView,
  SeriesAttachedParameter,
  SeriesType,
  Time,
} from 'lightweight-charts'
import type { ChartZoneView } from '@/utils/chartAdapter'

interface BandCoords {
  y1: number
  y2: number
  color: string
  label: string
}

class ZonePaneRenderer implements IPrimitivePaneRenderer {
  private _bands: BandCoords[]

  constructor(bands: BandCoords[]) {
    this._bands = bands
  }

  draw(target: {
    useBitmapCoordinateSpace: (
      fn: (scope: {
        context: CanvasRenderingContext2D
        bitmapSize: { width: number; height: number }
        horizontalPixelRatio: number
        verticalPixelRatio: number
      }) => void
    ) => void
  }): void {
    target.useBitmapCoordinateSpace((scope) => {
      const ctx = scope.context
      for (const band of this._bands) {
        const yTop = Math.min(band.y1, band.y2) * scope.verticalPixelRatio
        const yBot = Math.max(band.y1, band.y2) * scope.verticalPixelRatio
        const height = Math.max(1, yBot - yTop)
        ctx.fillStyle = band.color
        ctx.fillRect(0, yTop, scope.bitmapSize.width, height)
        ctx.fillStyle =
          band.color.replace(/[\d.]+\)$/, '0.85)') || 'rgba(100, 116, 139, 0.85)'
        ctx.font = `${11 * scope.verticalPixelRatio}px sans-serif`
        ctx.textBaseline = 'top'
        ctx.fillText(
          band.label,
          8 * scope.horizontalPixelRatio,
          yTop + 2 * scope.verticalPixelRatio
        )
      }
    })
  }
}

class ZonePaneView implements IPrimitivePaneView {
  private _source: ZoneBandsPrimitive
  private _bands: BandCoords[] = []

  constructor(source: ZoneBandsPrimitive) {
    this._source = source
  }

  update(): void {
    this._bands = this._source.bandCoordinates()
  }

  renderer(): IPrimitivePaneRenderer | null {
    if (this._bands.length === 0) return null
    return new ZonePaneRenderer(this._bands)
  }
}

/**
 * Draws support/resistance bands as full-width rectangles on the candle series.
 */
export class ZoneBandsPrimitive implements ISeriesPrimitive<Time> {
  private _chart: IChartApi | null = null
  private _series: ISeriesApi<SeriesType, Time> | null = null
  private _requestUpdate: (() => void) | null = null
  private _zones: ChartZoneView[] = []
  private readonly _paneViews: ZonePaneView[]

  constructor() {
    this._paneViews = [new ZonePaneView(this)]
  }

  attached(param: SeriesAttachedParameter<Time, SeriesType>): void {
    this._chart = param.chart
    this._series = param.series
    this._requestUpdate = param.requestUpdate
  }

  detached(): void {
    this._chart = null
    this._series = null
    this._requestUpdate = null
  }

  updateAllViews(): void {
    for (const view of this._paneViews) {
      view.update()
    }
  }

  paneViews(): readonly IPrimitivePaneView[] {
    return this._paneViews
  }

  setZones(zones: ChartZoneView[]): void {
    this._zones = zones
    this._requestUpdate?.()
  }

  bandCoordinates(): BandCoords[] {
    if (!this._series) return []
    const result: BandCoords[] = []
    for (const zone of this._zones) {
      const y1 = this._series.priceToCoordinate(zone.high)
      const y2 = this._series.priceToCoordinate(zone.low)
      if (y1 == null || y2 == null) continue
      result.push({
        y1,
        y2,
        color: zone.color,
        label: zone.label,
      })
    }
    return result
  }
}
