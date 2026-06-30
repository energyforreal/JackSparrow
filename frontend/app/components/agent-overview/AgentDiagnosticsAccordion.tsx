'use client'

import { memo } from 'react'
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion'
import type { AgentOverviewView } from '@/utils/agent-overview/types'

export const AgentDiagnosticsAccordion = memo(function AgentDiagnosticsAccordion({
  view,
  onOpenAnalysis,
}: {
  view: AgentOverviewView
  onOpenAnalysis?: () => void
}) {
  const d = view.diagnostics
  if (!d.hasContent) return null

  return (
    <Accordion type="single" collapsible defaultValue="">
      <AccordionItem value="diagnostics" className="border-none">
        <AccordionTrigger className="text-sm py-2 hover:no-underline">
          Technical diagnostics
        </AccordionTrigger>
        <AccordionContent className="text-xs space-y-3 text-muted-foreground">
          {d.agentContext && (
            <div>
              <p className="font-medium text-foreground text-sm">Agent context</p>
              <p>{d.agentContext}</p>
            </div>
          )}
          {d.hypotheses.length > 0 && (
            <div>
              <p className="font-medium text-foreground text-sm">Hypotheses</p>
              <ul className="list-disc list-inside space-y-0.5">
                {d.hypotheses.map((h) => (
                  <li key={h}>{h}</li>
                ))}
              </ul>
            </div>
          )}
          {d.modelConsensus && (
            <div>
              <p className="font-medium text-foreground text-sm">Model consensus</p>
              <p>{d.modelConsensus}</p>
            </div>
          )}
          {d.reflection && (
            <div>
              <p className="font-medium text-foreground text-sm">Reflection</p>
              <p>{d.reflection}</p>
            </div>
          )}
          {d.hasReasoningChain && onOpenAnalysis && (
            <button
              type="button"
              className="text-primary text-sm underline-offset-2 hover:underline"
              onClick={onOpenAnalysis}
            >
              Full rationale → Analysis
            </button>
          )}
        </AccordionContent>
      </AccordionItem>
    </Accordion>
  )
})
