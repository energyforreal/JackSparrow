import type { AgentOverviewInput, MarketEventView } from './types'

export function resolveRecentEvents(input: AgentOverviewInput, limit = 5): MarketEventView[] {
  const tail = input.signal?.narrative_tail
  if (!tail?.length) return []

  return [...tail]
    .slice(-limit)
    .reverse()
    .map((ev, i) => {
      const eventType = String(ev.event_type ?? 'event')
      return {
        eventType,
        timestamp: String(ev.timestamp ?? ''),
        label: eventType.replace(/_/g, ' '),
      }
    })
}
