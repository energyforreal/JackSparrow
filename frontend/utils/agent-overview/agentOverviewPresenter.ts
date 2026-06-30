import type {
  AgentOverviewView,
  EvidenceStatus,
  GateStatus,
  QualitativeLevel,
  ReadinessLabel,
} from './types'

export type ColorToken = 'success' | 'warning' | 'error' | 'muted' | 'info'

export interface PresentedHero {
  directionLabel: string
  lifecycleLabel: string
  fsmLabel: string | null
  runtimeLabel: string | null
  tradeScoreText: string | null
  tradeScorePassed: boolean | null
  confidenceText: string
  regimeText: string | null
  directionColor: ColorToken
  lifecycleColor: ColorToken
  minHeight: string
}

export interface PresentedReadiness {
  label: string
  labelColor: ColorToken
  blockedReason: string | null
  subMetrics: { label: string; value: string }[]
  minHeight: string
}

export interface PresentedGateRow {
  label: string
  statusIcon: 'check' | 'x' | 'minus'
  color: ColorToken
}

export interface PresentedEvidenceRow {
  label: string
  statusIcon: 'check' | 'x' | 'minus'
  color: ColorToken
  detail: string | null
}

export interface PresentedConfidencePillar {
  label: string
  level: string
  color: ColorToken
}

export interface PresentedScoreBar {
  label: string
  valueText: string
  percent: number
  color: ColorToken
}

export interface PresentedMarketEvent {
  time: string
  label: string
}

export interface PresentedOps {
  show: boolean
  lines: { label: string; value: string; color: ColorToken }[]
}

export interface AgentOverviewPresentation {
  hero: PresentedHero
  readiness: PresentedReadiness
  narrative: { text: string; sourceLabel: string | null }
  gates: { tradeAllowed: boolean; setupType: string | null; rows: PresentedGateRow[]; visible: boolean }
  evidence: { rows: PresentedEvidenceRow[]; visible: boolean }
  confidence: { aggregateText: string; pillars: PresentedConfidencePillar[]; visible: boolean }
  scoreBreakdown: {
    totalText: string
    passed: boolean | null
    bars: PresentedScoreBar[]
    visible: boolean
  }
  recentMarketEvents: { events: PresentedMarketEvent[]; visible: boolean }
  diagnostics: { visible: boolean; hasContent: boolean; hasReasoningChain: boolean }
  ops: PresentedOps
  sectionMinHeights: Record<string, string>
}

function readinessColor(label: ReadinessLabel): ColorToken {
  switch (label) {
    case 'Ready':
    case 'Managing':
      return 'success'
    case 'Executing':
      return 'info'
    case 'Blocked':
      return 'error'
    case 'ExitReady':
      return 'warning'
    default:
      return 'warning'
  }
}

function directionColor(direction: string): ColorToken {
  if (direction.includes('LONG')) return 'success'
  if (direction.includes('SHORT')) return 'error'
  return 'muted'
}

function gateStatusIcon(status: GateStatus): 'check' | 'x' | 'minus' {
  if (status === 'pass') return 'check'
  if (status === 'fail') return 'x'
  return 'minus'
}

function gateColor(status: GateStatus): ColorToken {
  if (status === 'pass') return 'success'
  if (status === 'fail') return 'error'
  return 'muted'
}

function evidenceIcon(status: EvidenceStatus): 'check' | 'x' | 'minus' {
  if (status === 'support') return 'check'
  if (status === 'against') return 'x'
  return 'minus'
}

function evidenceColor(status: EvidenceStatus): ColorToken {
  if (status === 'support') return 'success'
  if (status === 'against') return 'error'
  return 'muted'
}

function qualitativeColor(level: QualitativeLevel): ColorToken {
  switch (level) {
    case 'Excellent':
    case 'High':
      return 'success'
    case 'Good':
    case 'Medium':
      return 'warning'
    case 'Weak':
    case 'Blocked':
      return 'error'
    default:
      return 'muted'
  }
}

function formatTime(iso: string): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  } catch {
    return iso.slice(11, 16) || iso
  }
}

export function presentAgentOverview(view: AgentOverviewView): AgentOverviewPresentation {
  const hero: PresentedHero = {
    directionLabel: view.hero.directionLabel,
    lifecycleLabel: view.hero.lifecycleLabel,
    fsmLabel: view.hero.fsmLabel || null,
    runtimeLabel: view.hero.runtimeLabel,
    tradeScoreText:
      view.hero.tradeScore != null ? `${Math.round(view.hero.tradeScore)}` : null,
    tradeScorePassed: view.hero.tradeScorePassed,
    confidenceText: `${Math.round(view.hero.confidencePercent)}%`,
    regimeText: view.hero.regime ? `${view.hero.regime} regime` : null,
    directionColor: directionColor(view.hero.direction),
    lifecycleColor: readinessColor(view.readiness.label),
    minHeight: 'min-h-[140px]',
  }

  const readiness: PresentedReadiness = {
    label: view.readiness.label,
    labelColor: readinessColor(view.readiness.label),
    blockedReason: view.readiness.blockedReason,
    subMetrics: view.readiness.subMetrics.map((m) => ({
      label: m.label,
      value: m.value,
    })),
    minHeight: 'min-h-[72px]',
  }

  return {
    hero,
    readiness,
    narrative: {
      text: view.narrative.text,
      sourceLabel: view.narrative.source === 'backend' ? null : 'Synthesized assessment',
    },
    gates: {
      tradeAllowed: view.gates.tradeAllowed,
      setupType: view.gates.setupType,
      rows: view.gates.rows.map((r) => ({
        label: r.label,
        statusIcon: gateStatusIcon(r.status),
        color: gateColor(r.status),
      })),
      visible: view.showEntrySections,
    },
    evidence: {
      rows: view.evidence.rows.map((r) => ({
        label: r.label,
        statusIcon: evidenceIcon(r.status),
        color: evidenceColor(r.status),
        detail: r.detail ?? null,
      })),
      visible: true,
    },
    confidence: {
      aggregateText: `${Math.round(view.confidence.aggregatePercent)}%`,
      pillars: view.confidence.pillars.map((p) => ({
        label: p.label,
        level: p.level,
        color: qualitativeColor(p.level),
      })),
      visible: true,
    },
    scoreBreakdown: {
      totalText: `${view.scoreBreakdown.total}`,
      passed: view.scoreBreakdown.passed,
      bars: view.scoreBreakdown.bars.map((b) => ({
        label: b.label,
        valueText: `${Math.round(b.value)}`,
        percent: b.normalizedPercent,
        color: b.normalizedPercent >= 70 ? 'success' : b.normalizedPercent >= 40 ? 'warning' : 'muted',
      })),
      visible: view.scoreBreakdown.bars.length > 0,
    },
    recentMarketEvents: {
      events: view.recentMarketEvents.map((e) => ({
        time: formatTime(e.timestamp),
        label: e.label,
      })),
      visible: view.recentMarketEvents.length > 0,
    },
    diagnostics: {
      visible: view.diagnostics.hasContent,
      hasContent: view.diagnostics.hasContent,
      hasReasoningChain: view.diagnostics.hasReasoningChain,
    },
    ops: {
      show: view.ops.show,
      lines: [
        ...(view.ops.modeLabel
          ? [
              {
                label: 'Exchange',
                value: view.ops.tradingReady ? 'Ready' : 'Unavailable',
                color: (view.ops.tradingReady ? 'success' : 'error') as ColorToken,
              },
            ]
          : []),
        ...(view.ops.deltaLatencyMs != null
          ? [
              {
                label: 'Latency',
                value: `${view.ops.deltaLatencyMs}ms`,
                color: 'info' as ColorToken,
              },
            ]
          : []),
        ...(view.ops.executionP50Ms != null
          ? [
              {
                label: 'Risk→fill p50',
                value: `${view.ops.executionP50Ms}ms`,
                color: 'info' as ColorToken,
              },
            ]
          : []),
      ],
    },
    sectionMinHeights: {
      hero: 'min-h-[140px]',
      assessment: 'min-h-[64px]',
      readiness: 'min-h-[72px]',
      gates: 'min-h-[48px]',
      evidence: 'min-h-[48px]',
    },
  }
}
