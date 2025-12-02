'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { LearningUpdate } from '@/types'
import { TrendingUp, TrendingDown } from 'lucide-react'
import { cn } from '@/lib/utils'
import { formatDateTime } from '@/utils/formatters'

interface LearningReportProps {
  learningUpdate?: LearningUpdate
}

export function LearningReport({ learningUpdate }: LearningReportProps) {
  if (!learningUpdate) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Learning Report</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            No learning updates available
          </p>
        </CardContent>
      </Card>
    )
  }

  const formatDate = (date: Date) => {
    return formatDateTime(date)
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>Learning Report</CardTitle>
          <span className="text-xs text-muted-foreground">
            Updated: {formatDate(learningUpdate.updated_at)}
          </span>
        </div>
      </CardHeader>
      <CardContent className="space-y-6">
        {learningUpdate.key_lessons && learningUpdate.key_lessons.length > 0 && (
          <div>
            <h4 className="text-sm font-semibold mb-2">Key Lessons:</h4>
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

        {learningUpdate.model_weight_changes &&
          learningUpdate.model_weight_changes.length > 0 && (
            <div>
              <h4 className="text-sm font-semibold mb-2">Model Weight Changes:</h4>
              <div className="space-y-2">
                {learningUpdate.model_weight_changes.map((change, index) => (
                  <div
                    key={index}
                    className="flex items-center justify-between text-sm"
                  >
                    <span className="font-medium">{change.model_name}:</span>
                    <div className="flex items-center gap-2">
                      <span className="text-muted-foreground">
                        {change.old_weight.toFixed(2)} →
                      </span>
                      <span className="font-medium">
                        {change.new_weight.toFixed(2)}
                      </span>
                      <Badge
                        variant="outline"
                        className={cn(
                          'flex items-center gap-1',
                          change.change >= 0
                            ? 'text-success border-success'
                            : 'text-error border-error'
                        )}
                      >
                        {change.change >= 0 ? (
                          <TrendingUp className="h-3 w-3" />
                        ) : (
                          <TrendingDown className="h-3 w-3" />
                        )}
                        {change.change >= 0 ? '+' : ''}
                        {change.change.toFixed(2)}
                      </Badge>
                    </div>
                  </div>
                ))}
              </div>
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

