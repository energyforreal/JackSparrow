'use client'

import { useState } from 'react'
import { AgentStatus } from './AgentStatus'
import { PortfolioSummary } from './PortfolioSummary'
import { Header } from './Header'
import { SignalIndicator } from './SignalIndicator'
import { HealthMonitor } from './HealthMonitor'
import { ActivePositions } from './ActivePositions'
import { RecentTrades } from './RecentTrades'
import { PerformanceChart } from './PerformanceChart'
import { ReasoningChainView } from './ReasoningChainView'
import { TradingDecision } from './TradingDecision'
import { RealTimePrice } from './RealTimePrice'
import { ErrorBoundary } from './ErrorBoundary'
import { useTradingData } from '@/hooks/useTradingData'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from '@/components/ui/accordion'
import { AlertCircle, RefreshCw, TrendingUp, Activity, BarChart3, Settings } from 'lucide-react'

export function Dashboard() {
  // Use the unified trading data hook - replaces multiple specialized hooks
  const {
    signal,
    portfolio,
    recentTrades,
    modelData,
    health,
    agentState,
    isConnected,
    lastUpdate,
    isLoading,
    error
  } = useTradingData()

  // Extract positions from portfolio - much simpler now!
  const positions = portfolio?.positions || []

  // Simple state for UI-specific data (performance chart, etc.)
  const [performanceData] = useState<Array<{ date: string; value: number }>>([])

  return (
    <div className="min-h-screen bg-background">
      <Header isConnected={isConnected} />
      <div className="container mx-auto px-4 py-6 space-y-6">
        {error && (
          <Card className="border-destructive bg-destructive/5">
            <CardContent className="pt-6">
              <div className="flex items-start gap-3">
                <AlertCircle className="h-5 w-5 text-destructive flex-shrink-0 mt-0.5" />
                <div className="flex-1">
                  <div className="text-destructive font-semibold mb-1">
                    Connection Error
                  </div>
                  <div className="text-sm text-muted-foreground mb-2">
                    Unable to connect to real-time updates or load trading data.
                  </div>
                  <span className="text-xs text-muted-foreground block mb-4">
                    Ensure backend is running and WebSocket endpoint is accessible.
                  </span>
                  {error.message && (
                    <Accordion type="single" collapsible className="mb-4">
                      <AccordionItem value="details" className="border-none">
                        <AccordionTrigger className="text-xs py-1 hover:no-underline">
                          Technical details
                        </AccordionTrigger>
                        <AccordionContent className="text-xs font-mono text-muted-foreground break-all">
                          {error.message}
                        </AccordionContent>
                      </AccordionItem>
                    </Accordion>
                  )}
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => window.location.reload()}
                    className="flex items-center gap-2"
                  >
                    <RefreshCw className="h-4 w-4" />
                    Retry
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>
        )}

        <Tabs defaultValue="overview" className="space-y-6">
          <TabsList className="grid w-full grid-cols-4">
            <TabsTrigger value="overview" className="flex items-center gap-2">
              <TrendingUp className="h-4 w-4" />
              <span className="hidden sm:inline">Overview</span>
            </TabsTrigger>
            <TabsTrigger value="trading" className="flex items-center gap-2">
              <Activity className="h-4 w-4" />
              <span className="hidden sm:inline">Trading</span>
            </TabsTrigger>
            <TabsTrigger value="analysis" className="flex items-center gap-2">
              <BarChart3 className="h-4 w-4" />
              <span className="hidden sm:inline">Analysis</span>
            </TabsTrigger>
            <TabsTrigger value="system" className="flex items-center gap-2">
              <Settings className="h-4 w-4" />
              <span className="hidden sm:inline">System</span>
            </TabsTrigger>
          </TabsList>

          {/* Overview Tab */}
          <TabsContent value="overview" className="space-y-6">
            {/* Real-Time Price, Agent Status, Signal Indicator, Health Monitor */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
              <ErrorBoundary>
                <RealTimePrice symbol="BTCUSD" positions={positions} showPositionImpact={true} />
              </ErrorBoundary>
              <ErrorBoundary>
                <AgentStatus
                  state={agentState}
                  lastUpdate={lastUpdate}
                  isConnected={isConnected}
                />
              </ErrorBoundary>
              <ErrorBoundary>
                <SignalIndicator signal={signal || undefined} modelData={modelData || undefined} />
              </ErrorBoundary>
              <ErrorBoundary>
                <HealthMonitor health={health || undefined} />
              </ErrorBoundary>
            </div>

            {/* Portfolio Summary */}
            <ErrorBoundary>
              <PortfolioSummary portfolio={portfolio || undefined} isLoading={isLoading} />
            </ErrorBoundary>
          </TabsContent>

          {/* Trading Tab */}
          <TabsContent value="trading" className="space-y-6">
            {/* Active Positions and Recent Trades */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <ErrorBoundary>
                <ActivePositions positions={positions} isLoading={isLoading} />
              </ErrorBoundary>
              <ErrorBoundary>
                <RecentTrades trades={recentTrades} />
              </ErrorBoundary>
            </div>

            {/* Trading Decision */}
            <ErrorBoundary>
              <TradingDecision
                signal={signal}
                recentTrade={recentTrades?.[0] || null}
                paperTradingMode={true}
              />
            </ErrorBoundary>
          </TabsContent>

          {/* Analysis Tab */}
          <TabsContent value="analysis" className="space-y-6">
            {/* Performance Chart - Collapsible by default */}
            <Accordion type="single" collapsible defaultValue="">
              <AccordionItem value="performance-chart">
                <AccordionTrigger className="text-left">
                  <div className="flex items-center gap-2">
                    <BarChart3 className="h-4 w-4" />
                    Performance Chart
                  </div>
                </AccordionTrigger>
                <AccordionContent>
                  <ErrorBoundary>
                    <PerformanceChart data={performanceData} />
                  </ErrorBoundary>
                </AccordionContent>
              </AccordionItem>
            </Accordion>

            {/* Reasoning Chain Viewer with Integrated Model Reasoning */}
            <ErrorBoundary>
              <ReasoningChainView
                reasoningChain={signal?.reasoning_chain || []}
                chainMeta={signal?.reasoning_chain_full}
                overallConfidence={signal?.confidence}
                isLoading={isLoading}
                modelConsensus={signal?.model_consensus}
                individualModelReasoning={signal?.individual_model_reasoning}
                modelVersion={signal?.model_version ?? modelData?.model_version}
                inferenceLatencyMs={signal?.inference_latency_ms ?? modelData?.inference_latency_ms}
                inferenceMode={signal?.inference_mode ?? modelData?.inference_mode}
              />
            </ErrorBoundary>
          </TabsContent>

          {/* System Tab */}
          <TabsContent value="system" className="space-y-6">
            {/* Health Monitor (detailed system view) */}
            <ErrorBoundary>
              <HealthMonitor health={health || undefined} />
            </ErrorBoundary>

            {/* System Status Information */}
            <Card>
              <CardContent className="pt-6">
                <div className="text-center text-muted-foreground">
                  <Settings className="h-12 w-12 mx-auto mb-4 opacity-50" />
                  <p>System Health and Monitoring</p>
                  <p className="text-sm mt-2">Comprehensive system status and diagnostics</p>
                </div>
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      </div>
    </div>
  )
}

