import type { Signal } from '@/types'
import type { ModelConsensusSnapshot } from '@/hooks/useTradingData'
import type { HealthStatus } from '@/types'

export type AgentOverviewMode = 'entry' | 'managing' | 'flat'

export type ReadinessLabel =
  | 'Observing'
  | 'SetupForming'
  | 'Ready'
  | 'Executing'
  | 'Managing'
  | 'ExitReady'
  | 'Blocked'

export type QualitativeLevel = 'Excellent' | 'High' | 'Good' | 'Medium' | 'Weak' | 'Blocked' | 'Unknown'

export type GateStatus = 'pass' | 'fail' | 'unknown'

export type EvidenceStatus = 'support' | 'against' | 'neutral' | 'unknown'

export interface AgentOverviewInput {
  signal: Signal | null
  agentState: string
  health?: HealthStatus | null
  modelConsensus?: ModelConsensusSnapshot | null
}

export interface HeroView {
  direction: string
  directionLabel: string
  lifecycleLabel: string
  fsmLabel: string
  runtimeLabel: string | null
  tradeScore: number | null
  tradeScorePassed: boolean | null
  confidencePercent: number
  confidenceSource: 'reasoning' | 'policy'
  freshnessMs: number | null
  regime: string | null
}

export interface ReadinessSubMetric {
  key: string
  label: string
  value: string
  numericPercent?: number
}

export interface ReadinessView {
  label: ReadinessLabel
  blockedReason: string | null
  subMetrics: ReadinessSubMetric[]
}

export interface GateRowView {
  key: string
  label: string
  status: GateStatus
  detail?: string
}

export interface GatesView {
  tradeAllowed: boolean
  setupType: string | null
  rows: GateRowView[]
}

export interface EvidenceRowView {
  key: string
  label: string
  status: EvidenceStatus
  detail?: string
}

export interface EvidenceView {
  rows: EvidenceRowView[]
}

export interface ConfidencePillarView {
  key: string
  label: string
  level: QualitativeLevel
}

export interface ConfidenceView {
  aggregatePercent: number
  pillars: ConfidencePillarView[]
}

export interface ScoreBarView {
  key: string
  label: string
  value: number
  max: number
  normalizedPercent: number
}

export interface ScoreBreakdownView {
  total: number
  passed: boolean | null
  bars: ScoreBarView[]
}

export interface NarrativeView {
  text: string
  source: 'backend' | 'synthesized'
}

export interface MarketEventView {
  eventType: string
  timestamp: string
  label: string
}

export interface DiagnosticsView {
  hasContent: boolean
  hypotheses: string[]
  agentContext: string | null
  modelConsensus: string | null
  reflection: string | null
  hasReasoningChain: boolean
}

export interface OpsContextView {
  show: boolean
  tradingReady: boolean | null
  modeLabel: string | null
  deltaLatencyMs: number | null
  executionP50Ms: number | null
}

export interface AgentOverviewView {
  mode: AgentOverviewMode
  hero: HeroView
  readiness: ReadinessView
  gates: GatesView
  evidence: EvidenceView
  narrative: NarrativeView
  confidence: ConfidenceView
  scoreBreakdown: ScoreBreakdownView
  recentMarketEvents: MarketEventView[]
  diagnostics: DiagnosticsView
  ops: OpsContextView
  showEntrySections: boolean
  showManagingSections: boolean
}

export const TRADE_SCORE_COMPONENT_MAX: Record<string, number> = {
  thesis: 30,
  ml: 25,
  regime_fit: 15,
  liquidity: 15,
  structure: 10,
  gates: 10,
  multi_horizon: 10,
}
