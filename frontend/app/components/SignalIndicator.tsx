'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { ConfidenceProgress } from './ConfidenceProgress'
import { ModelConsensus, Signal, SignalType } from '@/types'
import { cn } from '@/lib/utils'
import { normalizeConfidenceToPercent, formatConfidence } from '@/utils/formatters'
import { DataFreshnessIndicator } from './DataFreshnessIndicator'
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from '@/components/ui/accordion'

interface SignalIndicatorProps {
  signal?: Signal
  modelData?: {
    model_consensus?: ModelConsensus[]
    inference_latency_ms?: number
    inference_source?: string
    inference_mode?: string
  } | null
}

const getSignalBadgeClasses = (signal: SignalType) => {
  switch (signal) {
    case 'STRONG_BUY':
      return 'bg-emerald-700 text-white hover:bg-emerald-800'
    case 'BUY':
      return 'bg-success text-white hover:bg-success/90'
    case 'HOLD':
      return 'bg-muted text-muted-foreground'
    case 'SELL':
      return 'bg-error text-white hover:bg-error/90'
    case 'STRONG_SELL':
      return 'bg-red-800 text-white hover:bg-red-900'
    default:
      return ''
  }
}

export function SignalIndicator({ signal, modelData }: SignalIndicatorProps) {
  if (!signal) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>AI Signal</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">No signal available</p>
          <p className="text-xs text-muted-foreground mt-2">
            Signals appear after a full prediction (market data → features → models). If the agent is connected but you still see this, check Delta/candles in logs or press <kbd className="px-1 rounded border border-border">P</kbd> for a manual prediction.
          </p>
        </CardContent>
      </Card>
    )
  }

  const overallConfidence = normalizeConfidenceToPercent(signal.confidence)
  const modelConsensus = signal.model_consensus && signal.model_consensus.length > 0
    ? signal.model_consensus
    : modelData?.model_consensus && modelData.model_consensus.length > 0
      ? modelData.model_consensus
      : []
  const latencyMs = signal.inference_latency_ms ?? modelData?.inference_latency_ms
  const inferenceMode = signal.inference_mode ?? modelData?.inference_mode
  const inferenceSource = signal.inference_source ?? modelData?.inference_source

  let inferenceBadgeText: string | null = null
  if (inferenceMode === 'fallback') inferenceBadgeText = 'Agent fallback'
  else if (inferenceMode === 'degraded') inferenceBadgeText = 'Degraded'
  else if (inferenceMode === 'primary' && inferenceSource === 'model_service')
    inferenceBadgeText = 'Model service'
  else if (!inferenceMode && inferenceSource === 'agent') inferenceBadgeText = 'Agent'
  else if (inferenceSource) inferenceBadgeText = inferenceSource.replace(/_/g, ' ')
  else if (inferenceMode === 'primary') inferenceBadgeText = 'Primary'
  else if (inferenceMode) inferenceBadgeText = inferenceMode

  const showInferenceBadge =
    inferenceMode === 'fallback' ||
    inferenceMode === 'degraded' ||
    Boolean(inferenceSource) ||
    Boolean(inferenceBadgeText)

  /** Agent step 6 floors final confidence to ~50% when all model confidences are zero (see reasoning_engine). */
  const modelsAllNearZeroConfidence =
    modelConsensus.length > 0 &&
    modelConsensus.every((m) => normalizeConfidenceToPercent(m.confidence) < 1)
  const overallNearCalibrationFloor =
    overallConfidence >= 49 && overallConfidence <= 51
  const showConfidenceCalibFallback =
    modelsAllNearZeroConfidence && overallNearCalibrationFloor

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle>AI Signal</CardTitle>
          {(showInferenceBadge && inferenceBadgeText) && (
            <Badge variant="outline" className="text-xs font-normal">
              {inferenceBadgeText}
            </Badge>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-center gap-4">
          {(() => {
            const isStrong =
              signal.signal === 'STRONG_BUY' || signal.signal === 'STRONG_SELL'
            return (
              <span className="relative inline-flex rounded-md">
                {isStrong && (
                  <span
                    className="absolute inset-0 rounded-md animate-ping opacity-30 bg-current"
                    aria-hidden
                  />
                )}
                <Badge
                  className={cn(
                    'relative px-4 py-2 text-base',
                    getSignalBadgeClasses(signal.signal)
                  )}
                  aria-label={`Trading signal: ${signal.signal}`}
                >
                  {signal.signal ? signal.signal.toString().replace('_', ' ') : 'Unknown'}
                </Badge>
              </span>
            )
          })()}
          {latencyMs != null && (
            <span className="text-xs text-muted-foreground">Latency: {Math.round(latencyMs)}ms</span>
          )}
          <div className="flex-1">
            <div className="flex justify-between text-sm mb-1">
              <span className="text-muted-foreground" title="Calibrated across the 6-step reasoning pipeline (may differ from raw model scores)">
                Reasoning confidence
              </span>
              <span className="font-medium">
                {formatConfidence(overallConfidence)}
              </span>
            </div>
            <ConfidenceProgress 
              value={overallConfidence}
              className="h-2" 
            />
            <p className="text-[10px] text-muted-foreground mt-1 leading-tight">
              Blended and calibrated in the agent; not a simple average of the rows below.
            </p>
          </div>
        </div>

        {showConfidenceCalibFallback && (
          <div
            role="status"
            className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-muted-foreground"
          >
            <span className="font-medium text-foreground">Calibration fallback active:</span>{' '}
            Top confidence reflects the agent&apos;s neutral floor because every model row shows ~0%
            (often after an inference error or failed consensus weights). Use{' '}
            <span className="font-medium text-foreground">System Health → model_nodes</span> and agent logs if this persists.
          </div>
        )}

        {(signal.expected_return != null ||
          signal.threshold != null ||
          signal.regime != null ||
          Boolean(signal.v43_gate_reject) ||
          signal.mcp_tanh_prediction != null ||
          signal.edge != null) && (
          <div className="rounded-md border border-border/60 bg-muted/30 px-3 py-2 text-xs text-muted-foreground space-y-1">
            <p className="font-medium text-foreground">JackSparrow v43</p>
            <p className="text-[10px] leading-tight italic">
              Primary economics: expected return vs threshold on simple-return scale (~120×5m forward in
              training).
            </p>
            <ul className="list-inside list-disc space-y-0.5 tabular-nums">
              {signal.expected_return != null && Number.isFinite(Number(signal.expected_return)) && (
                <li>
                  Expected return:{' '}
                  <span className="text-foreground font-medium">
                    {Number(signal.expected_return).toFixed(5)}
                  </span>
                </li>
              )}
              {signal.threshold != null && Number.isFinite(Number(signal.threshold)) && (
                <li>
                  Threshold:{' '}
                  <span className="text-foreground">{Number(signal.threshold).toFixed(5)}</span>
                </li>
              )}
              {signal.regime != null && signal.regime !== '' && (
                <li>
                  Regime: <span className="text-foreground">{String(signal.regime)}</span>
                </li>
              )}
              {signal.v43_gate_reject != null && signal.v43_gate_reject !== '' && (
                <li>
                  Gate reject:{' '}
                  <span className="text-foreground">{String(signal.v43_gate_reject)}</span>
                </li>
              )}
              {((signal.mcp_tanh_prediction != null &&
                Number.isFinite(Number(signal.mcp_tanh_prediction))) ||
                (signal.edge != null && Number.isFinite(signal.edge))) && (
                <li className="text-[10px] list-none -ml-0.5 mt-1 text-muted-foreground/90">
                  MCP tanh (legacy):{' '}
                  <span className="font-mono">
                    {(signal.mcp_tanh_prediction != null &&
                    Number.isFinite(Number(signal.mcp_tanh_prediction))
                      ? Number(signal.mcp_tanh_prediction)
                      : Number(signal.edge)
                    ).toFixed(5)}
                  </span>
                </li>
              )}
            </ul>
          </div>
        )}

        {modelConsensus.length > 0 && (
          <div className="pt-2 border-t">
            <Accordion type="single" collapsible defaultValue="models">
              <AccordionItem value="models">
                <AccordionTrigger className="text-sm font-medium text-left">
                  <span className="block">
                    Individual Models ({modelConsensus.length})
                    <span className="block text-xs font-normal text-muted-foreground mt-0.5">
                      Raw model output confidence per ensemble member
                    </span>
                  </span>
                </AccordionTrigger>
                <AccordionContent>
                  <div className="space-y-3 mt-1">
                    {modelConsensus.map((model) => {
                      const percent = normalizeConfidenceToPercent(model.confidence)
                      return (
                        <div
                          key={model.model_name}
                          className="flex items-center justify-between gap-3 rounded-md border px-3 py-2"
                        >
                          <div className="min-w-0 flex-1">
                            <div className="text-sm font-medium truncate">
                              {model.model_name}
                            </div>
                            {model.expected_return != null &&
                              Number.isFinite(Number(model.expected_return)) && (
                                <div className="text-[10px] text-muted-foreground tabular-nums mt-0.5">
                                  E[R] simple: {Number(model.expected_return).toFixed(5)}
                                  {model.threshold != null &&
                                    Number.isFinite(Number(model.threshold)) && (
                                      <> | thr {Number(model.threshold).toFixed(5)}</>
                                    )}
                                </div>
                              )}
                            <div className="mt-1 flex items-center gap-3">
                              <span className="relative inline-flex rounded-md">
                                {(model.signal === 'STRONG_BUY' ||
                                  model.signal === 'STRONG_SELL') && (
                                  <span
                                    className="absolute inset-0 rounded-md animate-ping opacity-25 bg-current"
                                    aria-hidden
                                  />
                                )}
                                <Badge
                                  className={cn(
                                    'relative px-2 py-0.5 text-xs',
                                    getSignalBadgeClasses(model.signal)
                                  )}
                                >
                                  {model.signal.replace('_', ' ')}
                                </Badge>
                              </span>
                              <div className="flex items-center gap-2 flex-1">
                                <ConfidenceProgress
                                  value={percent}
                                  className="h-1.5"
                                />
                                <span className="text-xs text-muted-foreground tabular-nums">
                                  {formatConfidence(percent)}
                                </span>
                              </div>
                            </div>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </AccordionContent>
              </AccordionItem>
            </Accordion>
          </div>
        )}

        {signal.agent_decision_reasoning && (
          <div className="pt-2 border-t">
            <p className="text-sm font-medium mb-1">Agent Decision Reasoning</p>
            <p className="text-xs text-muted-foreground">{signal.agent_decision_reasoning}</p>
          </div>
        )}

        {signal.timestamp && (
          <DataFreshnessIndicator timestamp={signal.timestamp} />
        )}
      </CardContent>
    </Card>
  )
}

