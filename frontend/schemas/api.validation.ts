/**
 * Zod validation schemas for API responses.
 * 
 * These schemas provide runtime type validation and ensure that
 * backend API responses match expected types before being used in the frontend.
 */

import { z, ZodSchema, ZodError } from 'zod'

// Shared schemas
const DecimalSchema = z.number({ description: 'Decimal value serialized as float' });
const DateSchema = z
  .union([z.string().datetime(), z.date()], { description: 'ISO 8601 datetime string' });
const SignalTypeSchema = z.enum(['STRONG_BUY', 'BUY', 'HOLD', 'SELL', 'STRONG_SELL'], {
  description: 'Trading signal type',
});
const PositionStatusSchema = z.enum(['OPEN', 'CLOSED', 'LIQUIDATED'], {
  description: 'Position status',
});
const TradeStatusSchema = z.enum(['EXECUTED', 'PENDING', 'FAILED'], {
  description: 'Trade status',
});
const SideSchema = z.enum(['BUY', 'SELL', 'LONG', 'SHORT'], {
  description: 'Trading side',
});

// Service status
export const HealthServiceStatusSchema = z.object(
  {
    status: z.string({ description: 'Service status (up/down/degraded)' }),
    latency_ms: z.number({ description: 'Service latency in milliseconds' }).optional(),
    error: z.string({ description: 'Error message if service is down' }).optional(),
    details: z.record(z.unknown(), {
      description: 'Additional service details',
    }).optional(),
  },
  { description: 'Health service status' },
);

// Health response
export const HealthResponseSchema = z.object(
  {
    status: z.string({ description: 'Overall system status' }),
    health_score: z
      .number({ description: 'Health score (0.0 to 1.0)' })
      .min(0)
      .max(1),
    services: z.record(HealthServiceStatusSchema, {
      description: 'Status of individual services',
    }),
    agent_state: z.string({ description: 'Current agent state' }).optional(),
    degradation_reasons: z
      .array(z.string(), { description: 'Reasons for degraded status' })
      .default([]),
    timestamp: DateSchema,
  },
  { description: 'Health response' },
);

// Model prediction
export const ModelPredictionSchema = z.object({
  model_name: z.string().describe('Model name'),
  prediction: z.number().min(-1).max(1).describe('Prediction value (-1.0 to +1.0)'),
  confidence: z.number().min(0).max(1).describe('Confidence score (0.0 to 1.0)'),
  reasoning: z.string().describe('Human-readable reasoning'),
});

// Model consensus entry
export const ModelConsensusEntrySchema = z.object({
  model_name: z.string().describe('Model name'),
  signal: z.string().describe('Discrete trading signal derived from model prediction'),
  confidence: z.number().min(0).max(1).describe('Model confidence (0.0 to 1.0)'),
});

// Model reasoning entry
export const ModelReasoningEntrySchema = z.object({
  model_name: z.string().describe('Model name'),
  reasoning: z.string().describe("Natural language explanation of the model's prediction"),
  confidence: z.number().min(0).max(1).describe('Model confidence (0.0 to 1.0)'),
});

// Reasoning step
export const ReasoningStepSchema = z.object({
  step_number: z.number().describe('Step number in chain'),
  step_name: z.string().describe('Step name'),
  description: z.string().describe('Step description'),
  evidence: z.array(z.string()).default([]).describe('Evidence items'),
  confidence: z.number().min(0).max(1).describe('Step confidence (0.0 to 1.0)'),
  data_freshness_seconds: z.number().optional().describe('Seconds since market data was last updated'),
  similarity_score: z.number().min(0).max(1).optional().describe('Similarity score for historical context retrieval'),
  feature_quality_score: z.number().min(0).max(1).optional().describe('Feature quality score for situational assessment'),
});

// Reasoning chain
export const ReasoningChainSchema = z.object({
  chain_id: z.string().describe('Unique reasoning chain ID'),
  timestamp: DateSchema.describe('Chain creation timestamp'),
  steps: z.array(ReasoningStepSchema).describe('Reasoning steps'),
  conclusion: z.string().describe('Final conclusion'),
  final_confidence: z.number().min(0).max(1).describe('Final confidence score (0.0 to 1.0)'),
});

// Predict response
export const PredictResponseSchema = z.object(
  {
    signal: z.string({ description: 'Trading signal' }),
    confidence: z
      .number({ description: 'Confidence score (0.0 to 1.0)' })
      .min(0)
      .max(1),
    position_size: DecimalSchema.optional(),
    reasoning_chain: ReasoningChainSchema,
    model_predictions: z
      .array(ModelPredictionSchema, { description: 'Individual model predictions' }),
    model_consensus: z
      .array(ModelConsensusEntrySchema, {
        description: 'Per-model consensus-style signals used in the frontend',
      })
      .default([]),
    individual_model_reasoning: z
      .array(ModelReasoningEntrySchema, {
        description: 'Per-model natural language reasoning summaries',
      })
      .default([]),
    market_context: z
      .record(z.unknown(), { description: 'Market context used' })
      .default({}),
    timestamp: DateSchema,
  },
  { description: 'Predict response' },
);

// Trade response
export const TradeResponseSchema = z.object({
  trade_id: z.string().describe('Unique trade ID'),
  symbol: z.string().describe('Trading symbol'),
  side: SideSchema.describe('Trade side'),
  quantity: DecimalSchema.describe('Trade quantity'),
  price: DecimalSchema.describe('Execution price'),
  status: TradeStatusSchema.describe('Trade status'),
  executed_at: DateSchema.describe('Execution timestamp'),
  reasoning_chain_id: z.string().optional().describe('Associated reasoning chain ID'),
});

// Position response
export const PositionResponseSchema = z.object({
  position_id: z.string().describe('Unique position ID'),
  symbol: z.string().describe('Trading symbol'),
  side: z.string().describe('Position side'),
  quantity: DecimalSchema.describe('Position quantity'),
  entry_price: DecimalSchema.describe('Entry price'),
  current_price: DecimalSchema.optional().describe('Current market price'),
  unrealized_pnl: DecimalSchema.optional().describe('Unrealized profit/loss'),
  status: PositionStatusSchema.describe('Position status'),
  opened_at: DateSchema.describe('Position open timestamp'),
  stop_loss: DecimalSchema.optional().describe('Stop loss price'),
  take_profit: DecimalSchema.optional().describe('Take profit price'),
});

// Portfolio summary response
export const PortfolioSummaryResponseSchema = z.object({
  total_value: DecimalSchema.describe('Total portfolio value'),
  available_balance: DecimalSchema.describe('Available balance'),
  open_positions: z.number().describe('Number of open positions'),
  total_unrealized_pnl: DecimalSchema.describe('Total unrealized profit/loss'),
  total_realized_pnl: DecimalSchema.describe('Total realized profit/loss'),
  positions: z.array(PositionResponseSchema).default([]).describe('Open positions'),
  timestamp: DateSchema.optional().describe('Response timestamp'),
});

// Market data response
export const MarketDataResponseSchema = z.object(
  {
    symbol: z.string({ description: 'Trading symbol' }),
    interval: z.string({ description: 'Time interval' }),
    candles: z
      .array(z.record(z.unknown()), { description: 'OHLCV candle data' }),
    latest_price: DecimalSchema,
    timestamp: DateSchema,
  },
  { description: 'Market data response' },
);

// Agent status response
export const AgentStatusResponseSchema = z.object({
  state: z.string().describe('Agent state'),
  last_update: DateSchema.optional().describe('Last update timestamp'),
  active_symbols: z.array(z.string()).default([]).describe('Active trading symbols'),
  model_count: z.number().describe('Number of active models'),
  health_status: z.string().describe('Agent health status'),
  message: z.string().optional().describe('Status message'),
});

// Simplified WebSocket message format (new)
const SimplifiedWebSocketEnvelopeSchema = z.object({
  type: z.enum(['data_update', 'agent_update', 'system_update', 'response', 'error']),
  resource: z.enum(['signal', 'portfolio', 'trade', 'market', 'performance', 'health', 'time', 'agent', 'model']).optional(),
  data: z.any().optional(),
  timestamp: z.string().optional(),
  sequence: z.number().optional(),
  source: z.string().optional(),
  request_id: z.string().optional(),
  server_timestamp_ms: z.number().optional(),
}).describe('Simplified WebSocket envelope format');

// Legacy WebSocket message types (for backward compatibility)
const LegacyWebSocketMessageSchema = z.union([
  z.object({
    type: z.literal('signal_update'),
    data: PredictResponseSchema,
  }),
  z.object({
    type: z.literal('trade_executed'),
    data: TradeResponseSchema,
  }),
  z.object({
    type: z.literal('portfolio_update'),
    data: PortfolioSummaryResponseSchema,
  }),
  z.object({
    type: z.literal('agent_state'),
    data: z.object({
      state: z.string(),
      timestamp: DateSchema.optional(),
      reason: z.string().optional(),
    }),
  }),
  z.object({
    type: z.literal('market_tick'),
    data: z.object({
      symbol: z.string(),
      price: DecimalSchema,
      volume: DecimalSchema.optional(),
      timestamp: DateSchema,
      change_24h_pct: z.number().optional(),
      high_24h: DecimalSchema.optional(),
      low_24h: DecimalSchema.optional(),
    }),
  }),
  z.object({
    type: z.literal('reasoning_chain_update'),
    data: z.object({
      reasoning_chain: z.array(ReasoningStepSchema).optional(),
      conclusion: z.string().optional(),
      final_confidence: z.number().optional(),
      timestamp: DateSchema.optional(),
    }),
  }),
  z.object({
    type: z.literal('model_prediction_update'),
    data: z.object({
      consensus_signal: z.number().optional(),
      consensus_confidence: z.number().optional(),
      individual_model_reasoning: z.array(z.unknown()).optional(),
      model_consensus: z.array(z.unknown()).optional(),
      model_predictions: z.array(z.unknown()).optional(),
      timestamp: DateSchema.optional(),
    }),
  }),
  z.object({
    type: z.literal('health_update'),
    data: HealthResponseSchema,
  }),
  z.object({
    type: z.literal('time_sync'),
    data: z.object({
      server_time: DateSchema,
      timestamp_ms: z.number(),
    }),
  }),
  z.object({
    type: z.literal('performance_update'),
    data: z.array(z.object({
      date: z.string(),
      value: z.number(),
    })),
  }),
  z.object({
    type: z.literal('subscribed'),
    channels: z.array(z.string()).optional(),
    data: z.object({
      channels: z.array(z.string()),
      message: z.string().optional(),
    }).optional(),
  }),
]);

// Combined WebSocket message schema (supports both formats)
export const WebSocketMessageSchema = z.union([
  SimplifiedWebSocketEnvelopeSchema,
  LegacyWebSocketMessageSchema,
]).describe('WebSocket message from backend (supports both simplified and legacy formats)');

// Type inference for runtime validation
export type HealthResponse = z.infer<typeof HealthResponseSchema>;
export type PredictResponse = z.infer<typeof PredictResponseSchema>;
export type TradeResponse = z.infer<typeof TradeResponseSchema>;
export type PositionResponse = z.infer<typeof PositionResponseSchema>;
export type PortfolioSummaryResponse = z.infer<typeof PortfolioSummaryResponseSchema>;
export type MarketDataResponse = z.infer<typeof MarketDataResponseSchema>;
export type AgentStatusResponse = z.infer<typeof AgentStatusResponseSchema>;
export type WebSocketMessage = z.infer<typeof WebSocketMessageSchema>;

/**
 * Validate API response against schema with error handling.
 * 
 * @param data - Data to validate
 * @param schema - Zod schema to validate against
 * @param context - Context for error messages
 * @returns Validated data or null if validation fails
 */
export function validateResponse<T>(
  data: unknown,
  schema: ZodSchema<T>,
  context: string = 'API response'
): T | null {
  try {
    return schema.parse(data);
  } catch (error) {
    const zodError = error as ZodError | undefined
    if (zodError && Array.isArray((zodError as any).issues)) {
      console.error(`Validation error in ${context}:`, {
        issues: (zodError as any).issues,
        data: data,
      });
    } else {
      console.error(`Unexpected error validating ${context}:`, error as Error);
    }
    return null;
  }
}
