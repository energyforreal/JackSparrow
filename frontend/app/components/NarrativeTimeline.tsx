'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

export interface NarrativeEvent {
  event_type?: string
  timestamp?: string
  bar_index?: number
  count?: number
  detail?: Record<string, unknown>
}

interface NarrativeTimelineProps {
  events?: NarrativeEvent[] | null
}

function formatTime(ts?: string) {
  if (!ts) return '—'
  try {
    const d = new Date(ts)
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  } catch {
    return ts.slice(11, 16) || ts
  }
}

export function NarrativeTimeline({ events }: NarrativeTimelineProps) {
  const list = events ?? []

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Market Narrative</CardTitle>
      </CardHeader>
      <CardContent>
        {list.length === 0 ? (
          <p className="text-sm text-muted-foreground">No narrative events yet.</p>
        ) : (
          <div className="h-48 pr-3 overflow-y-auto max-h-48">
            <ul className="space-y-2">
              {[...list].reverse().map((ev, i) => (
                <li key={`${ev.timestamp}-${ev.event_type}-${i}`} className="text-sm border-l-2 pl-3 border-muted">
                  <span className="text-muted-foreground font-mono text-xs mr-2">
                    {formatTime(ev.timestamp)}
                  </span>
                  <span className="capitalize">
                    {(ev.event_type || 'event').replace(/_/g, ' ')}
                    {ev.count != null ? ` (${ev.count})` : ''}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
