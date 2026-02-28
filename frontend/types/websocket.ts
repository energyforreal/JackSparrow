/**
 * Standardized WebSocket message types for simplified communication.
 *
 * This replaces the complex 10+ message type system with a unified envelope format.
 */

export enum WebSocketMessageType {
  DATA_UPDATE = 'data_update',      // Replaces signal_update, portfolio_update, trade_executed, etc.
  AGENT_UPDATE = 'agent_update',    // Replaces agent_state
  SYSTEM_UPDATE = 'system_update',  // Replaces health_update, time_sync
  RESPONSE = 'response',            // For request-response pattern
  ERROR = 'error'                   // Error messages
}

export enum WebSocketResource {
  SIGNAL = 'signal',           // Trading signals and reasoning
  PORTFOLIO = 'portfolio',     // Portfolio and positions
  TRADE = 'trade',            // Trade executions
  MARKET = 'market',          // Market data and ticks
  PERFORMANCE = 'performance', // Performance metrics
  HEALTH = 'health',          // System health
  TIME = 'time',              // Time synchronization
  AGENT = 'agent',            // Agent state
  MODEL = 'model'             // Model predictions
}

export interface WebSocketEnvelope {
  type: WebSocketMessageType
  resource?: WebSocketResource
  data?: any
  timestamp: string
  sequence?: number
  source: string
  request_id?: string
}

// Legacy message types (for backward compatibility during transition)
export interface LegacyWebSocketMessage {
  type: string
  data?: any
  [key: string]: any
}

// Union type for all WebSocket messages
export type WebSocketMessage = WebSocketEnvelope | LegacyWebSocketMessage

// Helper functions for type checking
export function isEnvelopeMessage(message: WebSocketMessage): message is WebSocketEnvelope {
  // Treat sequence as optional while requiring core envelope fields
  return 'type' in message && 'source' in message
}

export function isDataUpdateMessage(message: WebSocketMessage): boolean {
  if (isEnvelopeMessage(message)) {
    return message.type === WebSocketMessageType.DATA_UPDATE
  }
  return message.type === 'data_update'
}

export function isAgentUpdateMessage(message: WebSocketMessage): boolean {
  if (isEnvelopeMessage(message)) {
    return message.type === WebSocketMessageType.AGENT_UPDATE
  }
  return message.type === 'agent_update' || message.type === 'agent_state'
}

export function isSystemUpdateMessage(message: WebSocketMessage): boolean {
  if (isEnvelopeMessage(message)) {
    return message.type === WebSocketMessageType.SYSTEM_UPDATE
  }
  return ['system_update', 'health_update', 'time_sync'].includes(message.type)
}

// Message builders for frontend use
export class WebSocketMessageBuilder {
  static dataUpdate(resource: WebSocketResource, data: any, source: string = 'frontend'): WebSocketEnvelope {
    return {
      type: WebSocketMessageType.DATA_UPDATE,
      resource,
      data,
      timestamp: new Date().toISOString(),
      source
    }
  }

  static agentUpdate(data: any, source: string = 'frontend'): WebSocketEnvelope {
    return {
      type: WebSocketMessageType.AGENT_UPDATE,
      resource: WebSocketResource.AGENT,
      data,
      timestamp: new Date().toISOString(),
      source
    }
  }

  static systemUpdate(resource: WebSocketResource, data: any, source: string = 'frontend'): WebSocketEnvelope {
    return {
      type: WebSocketMessageType.SYSTEM_UPDATE,
      resource,
      data,
      timestamp: new Date().toISOString(),
      source
    }
  }

  static request(requestId: string, method: string, params?: any): WebSocketEnvelope {
    return {
      type: WebSocketMessageType.DATA_UPDATE,
      resource: WebSocketResource.AGENT,
      data: { method, params },
      timestamp: new Date().toISOString(),
      source: 'frontend',
      request_id: requestId
    }
  }

  static error(errorMessage: string, code: string = 'UNKNOWN_ERROR', requestId?: string): WebSocketEnvelope {
    return {
      type: WebSocketMessageType.ERROR,
      data: {
        error: {
          code,
          message: errorMessage,
          timestamp: new Date().toISOString()
        }
      },
      timestamp: new Date().toISOString(),
      source: 'system',
      request_id: requestId
    }
  }
}