'use client'

import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from '@/components/ui/accordion'
import type { AgentIntrospectionSnapshot, ReflectionSnapshot } from '@/types'
import { formatConfidence } from '@/utils/formatters'

interface SelfAwarenessPanelProps {
  introspection?: AgentIntrospectionSnapshot
  reflection?: ReflectionSnapshot | null
}

function formatPercent(value: number | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—'
  const pct = value <= 1 ? value * 100 : value
  return formatConfidence(pct)
}

export function SelfAwarenessPanel({ introspection, reflection }: SelfAwarenessPanelProps) {
  if (!introspection && !reflection) {
    return null
  }

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Self-Awareness</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-xs">
        {introspection && (
          <div className="rounded-md border border-border/60 bg-muted/30 px-3 py-2 space-y-1.5">
            <p className="font-medium text-foreground text-sm">Decision introspection</p>
            <ul className="grid gap-1 tabular-nums text-muted-foreground sm:grid-cols-2">
              <li>
                Policy:{' '}
                <span className="text-foreground font-medium">{introspection.policy_signal}</span>{' '}
                ({formatPercent(introspection.policy_confidence)})
              </li>
              <li>
                Mode: <span className="text-foreground">{introspection.policy_mode}</span>
              </li>
              <li>
                Agent state: <span className="text-foreground">{introspection.agent_state}</span>
              </li>
              {introspection.trade_score != null && (
                <li>
                  Trade score:{' '}
                  <span className="text-foreground">
                    {introspection.trade_score}
                    {introspection.trade_score_pass != null && (
                      <> ({introspection.trade_score_pass ? 'pass' : 'fail'})</>
                    )}
                  </span>
                </li>
              )}
              {introspection.v43_regime && (
                <li>
                  v43 regime: <span className="text-foreground">{introspection.v43_regime}</span>
                </li>
              )}
              {introspection.v43_gate_reject && (
                <li>
                  v43 gate: <span className="text-foreground">{introspection.v43_gate_reject}</span>
                </li>
              )}
              {introspection.portfolio_guard_action && (
                <li>
                  Portfolio guard:{' '}
                  <span className="text-foreground">{introspection.portfolio_guard_action}</span>
                </li>
              )}
              <li>
                Memory:{' '}
                <span className="text-foreground">
                  {introspection.memory_enabled ? 'on' : 'off'} (
                  {introspection.memory_context_count} contexts)
                </span>
              </li>
            </ul>
            {introspection.policy_reason_codes?.length > 0 && (
              <div className="flex flex-wrap gap-1 pt-1">
                {introspection.policy_reason_codes.slice(0, 6).map((code) => (
                  <Badge key={code} variant="outline" className="text-[10px] font-normal">
                    {code}
                  </Badge>
                ))}
              </div>
            )}
          </div>
        )}

        {reflection && (
          <div className="rounded-md border border-border/60 bg-muted/30 px-3 py-2 space-y-1.5">
            <div className="flex flex-wrap items-center gap-2">
              <p className="font-medium text-foreground text-sm">Post-trade reflection</p>
              {reflection.advisory_only && (
                <Badge variant="secondary" className="text-[10px] font-normal">
                  advisory only
                </Badge>
              )}
            </div>
            <ul className="grid gap-1 tabular-nums text-muted-foreground sm:grid-cols-2">
              <li>
                Quality:{' '}
                <span className="text-foreground font-medium">
                  {formatPercent(reflection.quality_score)}
                </span>
              </li>
              <li>
                Bucket: <span className="text-foreground">{reflection.calibration_bucket}</span>
              </li>
              <li>
                PnL:{' '}
                <span className={reflection.was_profitable ? 'text-emerald-600' : 'text-red-600'}>
                  {reflection.pnl.toFixed(2)}
                </span>
              </li>
              <li>
                Direction:{' '}
                <span className="text-foreground">
                  {reflection.direction_correct == null
                    ? 'n/a'
                    : reflection.direction_correct
                      ? 'aligned'
                      : 'misaligned'}
                </span>
              </li>
            </ul>
            {reflection.reason_codes?.length > 0 && (
              <Accordion type="single" collapsible>
                <AccordionItem value="reflection-codes" className="border-none">
                  <AccordionTrigger className="py-1 text-xs font-medium hover:no-underline">
                    Reason codes ({reflection.reason_codes.length})
                  </AccordionTrigger>
                  <AccordionContent>
                    <ul className="list-inside list-disc space-y-0.5 text-muted-foreground">
                      {reflection.reason_codes.map((code) => (
                        <li key={code}>{code}</li>
                      ))}
                    </ul>
                  </AccordionContent>
                </AccordionItem>
              </Accordion>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
