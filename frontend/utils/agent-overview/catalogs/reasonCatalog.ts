/** Maps trade_score.reason_codes, v43_gate_reject, policy codes → operator copy. */

const REASON_MAP: Record<string, string> = {
  score_thesis_active: 'Thesis supports active direction',
  score_ml_gated_confirms: 'ML ensemble supports direction',
  score_ml_gates_passed: 'ML gates passed',
  score_ml_ungated_skipped: 'ML confirmation not gated',
  score_liquidity_penalty: 'Liquidity conditions penalized score',
  score_chop_penalty: 'Choppy structure penalized score',
  score_multi_horizon_alignment: 'Multi-horizon models aligned',
  below_threshold: 'Expected return below execution threshold',
  liquidity_stressed: 'Liquidity stressed — entry blocked',
  structural_liquidity_stressed: 'Liquidity conditions unfavorable',
  structural_liquidity_thin: 'Liquidity too thin',
  structural_trend_neutral: 'Trend neutral — no directional setup',
  structural_no_valid_setup: 'No valid structural setup',
}

export function resolveReasonCopy(code: string): string {
  const key = code.trim()
  if (REASON_MAP[key]) return REASON_MAP[key]
  return key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

export function resolveReasonCopyList(codes: string[] | undefined): string[] {
  if (!codes?.length) return []
  return codes.map(resolveReasonCopy)
}
