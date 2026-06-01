'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { LearningUpdate } from '@/types'
import { formatDateTime } from '@/utils/formatters'

interface LearningReportProps {
  learningUpdate?: LearningUpdate
}

export function LearningReport({ learningUpdate }: LearningReportProps) {
  if (!learningUpdate) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Strategy Report</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            No strategy updates available
          </p>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>Strategy Report</CardTitle>
          <span className="text-xs text-muted-foreground">
            Updated: {formatDateTime(learningUpdate.updated_at)}
          </span>
        </div>
      </CardHeader>
      <CardContent className="space-y-6">
        {learningUpdate.key_lessons && learningUpdate.key_lessons.length > 0 && (
          <div>
            <h4 className="text-sm font-semibold mb-2">Observations:</h4>
            <ul className="space-y-1">
              {learningUpdate.key_lessons.map((lesson, index) => (
                <li key={index} className="text-sm text-muted-foreground flex items-start gap-2">
                  <span className="text-primary mt-1">•</span>
                  <span>{lesson}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {learningUpdate.strategy_adaptations &&
          learningUpdate.strategy_adaptations.length > 0 && (
            <div>
              <h4 className="text-sm font-semibold mb-2">Strategy Adaptations:</h4>
              <ul className="space-y-1">
                {learningUpdate.strategy_adaptations.map((adaptation, index) => (
                  <li
                    key={index}
                    className="text-sm text-muted-foreground flex items-start gap-2"
                  >
                    <span className="text-primary mt-1">•</span>
                    <span>{adaptation}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
      </CardContent>
    </Card>
  )
}
