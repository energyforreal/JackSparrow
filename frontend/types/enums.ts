/**
 * Shared enumerations for backend-frontend type synchronization.
 * 
 * These enums are derived from backend definitions and ensure that both
 * frontend and backend use the same values for signals, statuses, and states.
 */

/**
 * Trading signal types - must match backend signal definitions.
 * 
 * @see backend/services/agent_event_subscriber.py (valid_signals list)
 * @see backend/api/routes/trading.py (signal mapping logic)
 */
export const SIGNAL_TYPE_VALUES = ['STRONG_BUY', 'BUY', 'HOLD', 'SELL', 'STRONG_SELL'] as const;
export type SignalType = typeof SIGNAL_TYPE_VALUES[number];

export const isValidSignal = (value: unknown): value is SignalType => {
  return SIGNAL_TYPE_VALUES.includes(value as SignalType);
};

/**
 * Position status - must match backend PositionStatus enum.
 * 
 * @see backend/core/database.py (PositionStatus enum)
 */
export const POSITION_STATUS_VALUES = ['OPEN', 'CLOSED', 'LIQUIDATED'] as const;
export type PositionStatus = typeof POSITION_STATUS_VALUES[number];

export const isValidPositionStatus = (value: unknown): value is PositionStatus => {
  return POSITION_STATUS_VALUES.includes(value as PositionStatus);
};

/**
 * Trade status - must match backend TradeStatus enum.
 * 
 * @see backend/core/database.py (TradeStatus enum)
 */
export const TRADE_STATUS_VALUES = ['EXECUTED', 'PENDING', 'FAILED'] as const;
export type TradeStatus = typeof TRADE_STATUS_VALUES[number];

export const isValidTradeStatus = (value: unknown): value is TradeStatus => {
  return TRADE_STATUS_VALUES.includes(value as TradeStatus);
};

/**
 * Trade side - must match backend TradeSide enum.
 * 
 * @see backend/core/database.py (TradeSide enum)
 */
export const TRADE_SIDE_VALUES = ['BUY', 'SELL'] as const;
export type TradeSide = typeof TRADE_SIDE_VALUES[number];

export const isValidTradeSide = (value: unknown): value is TradeSide => {
  return TRADE_SIDE_VALUES.includes(value as TradeSide);
};

/**
 * Position side - can be LONG or SHORT.
 */
export const POSITION_SIDE_VALUES = ['LONG', 'SHORT'] as const;
export type PositionSide = typeof POSITION_SIDE_VALUES[number];

export const isValidPositionSide = (value: unknown): value is PositionSide => {
  return POSITION_SIDE_VALUES.includes(value as PositionSide);
};

/**
 * Agent state values - various states the agent can be in.
 */
export const AGENT_STATE_VALUES = [
  'UNKNOWN',
  'INITIALIZING',
  'MONITORING',
  'OBSERVING',
  'DECISION_MAKING',
  'EXECUTING',
  'PAUSED',
  'STOPPED',
  'ERROR',
] as const;
export type AgentState = typeof AGENT_STATE_VALUES[number];

export const isValidAgentState = (value: unknown): value is AgentState => {
  return AGENT_STATE_VALUES.includes(value as AgentState);
};

/**
 * Health status values.
 */
export const HEALTH_STATUS_VALUES = ['healthy', 'degraded', 'unhealthy'] as const;
export type HealthStatusType = typeof HEALTH_STATUS_VALUES[number];

export const isValidHealthStatus = (value: unknown): value is HealthStatusType => {
  return HEALTH_STATUS_VALUES.includes(value as HealthStatusType);
};

/**
 * Service status values.
 */
export const SERVICE_STATUS_VALUES = ['up', 'down', 'degraded', 'unknown'] as const;
export type ServiceStatusType = typeof SERVICE_STATUS_VALUES[number];

export const isValidServiceStatus = (value: unknown): value is ServiceStatusType => {
  return SERVICE_STATUS_VALUES.includes(value as ServiceStatusType);
};

/**
 * Validate and normalize a signal type.
 *
 * @param signal Raw signal value from backend
 * @returns Valid SignalType or null if invalid
 */
export function normalizeSignalType(signal: unknown): SignalType | null {
  if (isValidSignal(signal)) {
    return signal;
  }
  console.warn(`Invalid signal type: ${signal}, treating as no signal`);
  return null;
}

/**
 * Get human-readable label for a signal type.
 */
export function getSignalLabel(signal: SignalType): string {
  const labels: Record<SignalType, string> = {
    'STRONG_BUY': 'Strong Buy',
    'BUY': 'Buy',
    'HOLD': 'Hold',
    'SELL': 'Sell',
    'STRONG_SELL': 'Strong Sell',
  };
  return labels[signal] || 'Unknown';
}

/**
 * Get color for a signal type (for UI rendering).
 */
export function getSignalColor(signal: SignalType): string {
  const colors: Record<SignalType, string> = {
    'STRONG_BUY': '#00c853',  // Green
    'BUY': '#66bb6a',         // Light Green
    'HOLD': '#ffa726',        // Orange
    'SELL': '#ef5350',        // Light Red
    'STRONG_SELL': '#c62828', // Dark Red
  };
  return colors[signal] || '#9e9e9e';
}

/**
 * Get numeric confidence threshold for signal strength.
 * Used for interpreting raw predictions to signals.
 */
export const SIGNAL_CONFIDENCE_THRESHOLDS = {
  STRONG_BUY_MIN: 0.8,
  BUY_MIN: 0.65,
  SELL_MAX: 0.35,
  STRONG_SELL_MAX: 0.2,
} as const;
