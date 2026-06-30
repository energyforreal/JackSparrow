import type { HealthStatus, Signal } from '@/types'

const BASE_TS = '2026-06-30T12:00:00.000Z'

function gates(
  categories: Record<string, boolean>,
  tradeAllowed = true,
  setupType = 'trend_continuation'
) {
  return {
    trade_allowed: tradeAllowed,
    categories,
    block_reasons: tradeAllowed ? [] : ['structural_no_valid_setup'],
    setup_type: setupType,
  }
}

function tradeScore(
  score: number,
  passed: boolean,
  components: Record<string, number>,
  reason_codes: string[] = []
) {
  return { score, passed, components, reason_codes }
}

const ALL_GATES_PASS = gates({
  trend: true,
  structure: true,
  breakout: true,
  liquidity: true,
  volatility: true,
  risk: true,
})

const LIQUIDITY_FAIL = gates(
  {
    trend: true,
    structure: true,
    breakout: false,
    liquidity: false,
    volatility: true,
    risk: true,
  },
  false,
  'none'
)

export interface AgentOverviewFixture {
  id: string
  label: string
  signal: Signal
  agentState: string
  health?: HealthStatus
}

export const LONG_WATCHING: AgentOverviewFixture = {
  id: 'LONG_WATCHING',
  label: 'LONG · Watching',
  agentState: 'OBSERVING',
  signal: {
    signal: 'LONG',
    confidence: 62,
    final_confidence: 0.56,
    policy_confidence: 0.62,
    symbol: 'BTCUSD',
    timestamp: BASE_TS,
    server_timestamp_ms: Date.parse(BASE_TS),
    fsm_state: 'Watching',
    position_lifecycle: 'watching',
    regime: 'neutral',
    expected_return: 0.0012,
    threshold: 0.0008,
    economic_edge: 0.0004,
    entry_proba_margin: 0.08,
    is_actionable_entry: false,
    structural_gates: ALL_GATES_PASS,
    trade_score: tradeScore(
      78,
      true,
      { thesis: 22, ml: 18, regime_fit: 8, liquidity: 15, structure: 10, gates: 5 },
      ['score_thesis_active', 'score_ml_gated_confirms']
    ),
    market_state: {
      trend: 'bullish',
      trend_strength: 'moderate',
      liquidity: 'healthy',
      volatility: 'stable',
      confidence: 'medium',
      breakout_status: 'none',
      retest_status: 'none',
    },
    narrative_tail: [
      { event_type: 'trend_shift_bullish', timestamp: '2026-06-30T11:45:00.000Z' },
    ],
    agent_decision_reasoning:
      'Market remains range-bound with a slight bullish bias. Waiting for stronger entry confirmation.',
  },
}

export const SHORT_SETUP_FORMING: AgentOverviewFixture = {
  id: 'SHORT_SETUP_FORMING',
  label: 'SHORT · Setup forming',
  agentState: 'ANALYZING',
  signal: {
    signal: 'SHORT',
    confidence: 55,
    final_confidence: 0.52,
    symbol: 'BTCUSD',
    timestamp: BASE_TS,
    fsm_state: 'SetupForming',
    position_lifecycle: 'watching',
    structural_gates: gates({
      trend: true,
      structure: true,
      breakout: false,
      liquidity: true,
      volatility: true,
      risk: true,
    }),
    trade_score: tradeScore(65, true, {
      thesis: 18,
      ml: 12,
      regime_fit: 8,
      liquidity: 15,
      structure: 10,
      gates: 2,
    }),
    market_state: {
      trend: 'bearish',
      momentum: 'decreasing',
      liquidity: 'healthy',
      confidence: 'medium',
    },
  },
}

export const HOLD_OBSERVING: AgentOverviewFixture = {
  id: 'HOLD_OBSERVING',
  label: 'HOLD · Observing',
  agentState: 'OBSERVING',
  signal: {
    signal: 'HOLD',
    confidence: 40,
    final_confidence: 0.38,
    symbol: 'BTCUSD',
    timestamp: BASE_TS,
    is_actionable_entry: false,
    fsm_state: 'Watching',
    position_lifecycle: 'watching',
    v43_gate_reject: 'below_threshold',
    structural_gates: gates({
      trend: false,
      structure: true,
      breakout: false,
      liquidity: true,
      volatility: true,
      risk: true,
    }),
    trade_score: tradeScore(28, false, { thesis: 0, ml: 8, liquidity: 15, structure: 5 }),
  },
}

export const LONG_ENTRY_READY: AgentOverviewFixture = {
  id: 'LONG_ENTRY_READY',
  label: 'LONG · Entry ready',
  agentState: 'DELIBERATING',
  signal: {
    signal: 'LONG',
    confidence: 72,
    final_confidence: 0.68,
    policy_confidence: 0.72,
    symbol: 'BTCUSD',
    timestamp: BASE_TS,
    fsm_state: 'EntryReady',
    position_lifecycle: 'entry_ready',
    is_actionable_entry: true,
    structural_gates: ALL_GATES_PASS,
    expected_return: 0.0015,
    threshold: 0.0008,
    economic_edge: 0.0007,
    entry_proba_margin: 0.22,
    trade_score: tradeScore(
      93,
      true,
      { thesis: 28, ml: 22, regime_fit: 12, liquidity: 15, structure: 10, gates: 6 },
      ['score_thesis_active', 'score_ml_gated_confirms', 'score_ml_gates_passed']
    ),
    agent_decision_reasoning:
      'Expected return exceeds execution threshold. Structural gates pass. Awaiting entry timing confirmation.',
    narrative_tail: [
      { event_type: 'breakout_confirmed', timestamp: '2026-06-30T11:50:00.000Z' },
      { event_type: 'retest_successful', timestamp: '2026-06-30T11:55:00.000Z' },
    ],
  },
  health: {
    status: 'healthy',
    health_score: 92,
    trading_ready: true,
    trading_mode: 'testnet',
    services: {
      database: { status: 'up', latency_ms: 5 },
      delta_api: { status: 'up', latency_ms: 14 },
      execution_latency: {
        status: 'up',
        details: { risk_approved_to_fill_ms: { count: 12, p50: 14, p95: 28 } },
      },
    },
  },
}

export const LONG_MANAGING: AgentOverviewFixture = {
  id: 'LONG_MANAGING',
  label: 'LONG · Managing',
  agentState: 'MONITORING_POSITION',
  signal: {
    signal: 'LONG',
    confidence: 65,
    final_confidence: 0.6,
    symbol: 'BTCUSD',
    timestamp: BASE_TS,
    fsm_state: 'Managing',
    position_lifecycle: 'managing',
    thesis_health: 'healthy',
    is_actionable_entry: false,
    structural_gates: ALL_GATES_PASS,
    trade_score: tradeScore(88, true, {
      thesis: 25,
      ml: 20,
      liquidity: 15,
      structure: 10,
      gates: 8,
    }),
    agent_decision_reasoning:
      'Position thesis remains intact. Monitoring continuation and risk parameters.',
  },
  health: {
    status: 'healthy',
    health_score: 90,
    trading_ready: true,
    trading_mode: 'testnet',
    services: {
      delta_api: { status: 'up', latency_ms: 16 },
      execution_latency: {
        status: 'up',
        details: { risk_approved_to_fill_ms: { count: 8, p50: 16, p95: 32 } },
      },
    },
  },
}

export const LONG_EXIT_READY: AgentOverviewFixture = {
  id: 'LONG_EXIT_READY',
  label: 'LONG · Exit ready',
  agentState: 'MONITORING_POSITION',
  signal: {
    signal: 'HOLD',
    confidence: 58,
    final_confidence: 0.55,
    symbol: 'BTCUSD',
    timestamp: BASE_TS,
    fsm_state: 'ExitReady',
    position_lifecycle: 'exit_ready',
    thesis_health: 'weakening',
    is_actionable_entry: false,
    structural_gates: gates({
      trend: true,
      structure: false,
      breakout: false,
      liquidity: true,
      volatility: true,
      risk: true,
    }),
    trade_score: tradeScore(45, false, { thesis: 10, ml: 8, structure: 0, liquidity: 15 }),
    agent_decision_reasoning:
      'Thesis weakening. Evaluating exit conditions while protecting open profit.',
  },
}

export const BLOCKED_GATE_FAIL: AgentOverviewFixture = {
  id: 'BLOCKED_GATE_FAIL',
  label: 'Blocked · Gate fail',
  agentState: 'OBSERVING',
  signal: {
    signal: 'LONG',
    confidence: 48,
    final_confidence: 0.45,
    symbol: 'BTCUSD',
    timestamp: BASE_TS,
    fsm_state: 'Watching',
    position_lifecycle: 'watching',
    is_actionable_entry: false,
    v43_gate_reject: 'liquidity_stressed',
    structural_gates: LIQUIDITY_FAIL,
    trade_score: tradeScore(
      42,
      false,
      { thesis: 15, ml: 10, liquidity: 0, structure: 5 },
      ['score_liquidity_penalty']
    ),
  },
}

export const AGENT_OVERVIEW_FIXTURES: AgentOverviewFixture[] = [
  LONG_WATCHING,
  SHORT_SETUP_FORMING,
  HOLD_OBSERVING,
  LONG_ENTRY_READY,
  LONG_MANAGING,
  LONG_EXIT_READY,
  BLOCKED_GATE_FAIL,
]

export const DEFAULT_MODEL_CONSENSUS = {
  signal: 'LONG' as const,
  confidence: 0.67,
}
