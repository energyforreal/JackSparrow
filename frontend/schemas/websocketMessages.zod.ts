/**
 * Zod schemas for inbound WebSocket messages (FastAPI unified manager).
 * Kept permissive (passthrough) so unknown fields do not break the client.
 *
 * JSON Schema mirror: `websocket_message.schema.json` (same directory).
 */
import { z } from 'zod'

const passthroughObject = z.object({ type: z.string() }).passthrough()

export const WebSocketSimplifiedEnvelopeSchema = z
  .object({
    type: z.enum(['data_update', 'agent_update', 'system_update']),
    resource: z.string().optional(),
    data: z.unknown().optional(),
    payload: z.unknown().optional(),
    schema_version: z.number().int().positive().optional(),
    server_timestamp: z.union([z.string(), z.number()]).optional(),
    server_timestamp_ms: z.number().optional(),
  })
  .passthrough()

export const WebSocketResponseSchema = z
  .object({
    type: z.literal('response'),
    success: z.boolean().optional(),
    request_id: z.string().optional(),
    correlation_id: z.string().optional(),
    command: z.string().optional(),
    data: z.unknown().optional(),
    error: z.string().optional(),
    timestamp: z.string().optional(),
    schema_version: z.number().int().positive().optional(),
  })
  .passthrough()

export const WebSocketSubscribedSchema = z
  .object({
    type: z.literal('subscribed'),
    channels: z.array(z.string()).optional(),
    schema_version: z.number().int().positive().optional(),
  })
  .passthrough()

export const WebSocketUnsubscribedSchema = z
  .object({
    type: z.literal('unsubscribed'),
    channels: z.array(z.string()).optional(),
  })
  .passthrough()

export const WebSocketStateSchema = z
  .object({
    type: z.literal('state'),
    data: z.unknown().optional(),
  })
  .passthrough()

export const WebSocketErrorSchema = z
  .object({
    type: z.literal('error'),
    message: z.string().optional(),
  })
  .passthrough()

export const WebSocketAckSchema = z
  .object({
    type: z.literal('ack'),
  })
  .passthrough()

/** Union of known shapes; falls back to any object with a string `type`. */
export const WebSocketInboundSchema = z.union([
  WebSocketSimplifiedEnvelopeSchema,
  WebSocketResponseSchema,
  WebSocketSubscribedSchema,
  WebSocketUnsubscribedSchema,
  WebSocketStateSchema,
  WebSocketErrorSchema,
  WebSocketAckSchema,
  passthroughObject,
])

export type WebSocketInbound = z.infer<typeof WebSocketInboundSchema>

export function parseWebSocketInbound(raw: unknown): { ok: true; data: WebSocketInbound } | { ok: false; error: z.ZodError } {
  const r = WebSocketInboundSchema.safeParse(raw)
  return r.success ? { ok: true, data: r.data } : { ok: false, error: r.error }
}
