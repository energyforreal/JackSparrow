/**
 * Frontend communication logger utility.
 *
 * Provides structured logging for WebSocket messages, command requests/responses,
 * and data flows between frontend and backend services.
 */

// Configuration
const DEFAULT_MAX_PAYLOAD_SIZE = 10 * 1024; // 10KB
const DEFAULT_SENSITIVE_FIELDS = ['password', 'token', 'api_key', 'secret'];
const STORAGE_KEY = 'trading_agent_communication_logs';
const MAX_STORED_LOGS = 100;

// Types
interface CommunicationLogEntry {
  timestamp: string;
  service: 'frontend';
  direction: 'inbound' | 'outbound';
  protocol: 'websocket';
  message_type: string;
  resource?: string;
  correlation_id?: string;
  target: 'backend';
  payload_summary: {
    type: string;
    size_bytes: number;
    keys?: string[];
    length?: number;
    payload: any;
  };
  latency_ms?: number;
  error?: string;
  [key: string]: any;
}

interface LogConfig {
  enableLogging: boolean;
  enableStorage: boolean;
  maxPayloadSize: number;
  sensitiveFields: string[];
  maxStoredLogs: number;
}

// Global configuration
let config: LogConfig = {
  enableLogging: process.env.NODE_ENV === 'development', // Default to enabled in development
  enableStorage: false, // Disabled by default to avoid storage bloat
  maxPayloadSize: DEFAULT_MAX_PAYLOAD_SIZE,
  sensitiveFields: DEFAULT_SENSITIVE_FIELDS,
  maxStoredLogs: MAX_STORED_LOGS,
};

/**
 * Configure the communication logger
 */
export function configureLogger(newConfig: Partial<LogConfig>): void {
  config = { ...config, ...newConfig };
}

/**
 * Sanitize payload by removing or masking sensitive fields
 */
function sanitizePayload(payload: any, sensitiveFields: string[] = config.sensitiveFields): any {
  if (!payload) return payload;

  if (typeof payload === 'object' && payload !== null) {
    if (Array.isArray(payload)) {
      return payload.map(item => sanitizePayload(item, sensitiveFields));
    }

    const sanitized: any = {};
    for (const [key, value] of Object.entries(payload)) {
      if (sensitiveFields.some(field => key.toLowerCase().includes(field.toLowerCase()))) {
        sanitized[key] = '***REDACTED***';
      } else {
        sanitized[key] = sanitizePayload(value, sensitiveFields);
      }
    }
    return sanitized;
  }

  return payload;
}

/**
 * Truncate payload if it exceeds maximum size
 */
function truncatePayload(payload: any, maxSize: number = config.maxPayloadSize): any {
  if (!payload) return payload;

  const payloadStr = JSON.stringify(payload);
  if (payloadStr.length > maxSize) {
    return {
      truncated: true,
      size: payloadStr.length,
      content: payloadStr.substring(0, maxSize - 50) + '...[TRUNCATED]'
    };
  }

  return payload;
}

/**
 * Generate payload summary for logging
 */
function getPayloadSummary(payload: any): CommunicationLogEntry['payload_summary'] {
  if (payload === null || payload === undefined) {
    return { type: 'null', size_bytes: 0, payload };
  }

  const sanitized = sanitizePayload(payload);
  const truncated = truncatePayload(sanitized);

  const summary: CommunicationLogEntry['payload_summary'] = {
    type: Array.isArray(payload) ? 'array' : typeof payload,
    size_bytes: JSON.stringify(payload).length,
    payload: truncated
  };

  if (typeof payload === 'object' && payload !== null && !Array.isArray(payload)) {
    summary.keys = Object.keys(payload);
    summary.length = summary.keys.length;
  } else if (Array.isArray(payload)) {
    summary.length = payload.length;
    if (payload.length > 0 && typeof payload[0] === 'object') {
      summary.keys = Object.keys(payload[0]);
    }
  }

  return summary;
}

/**
 * Store log entry in browser storage (if enabled)
 */
function storeLogEntry(entry: CommunicationLogEntry): void {
  if (!config.enableStorage) return;

  try {
    const existing = localStorage.getItem(STORAGE_KEY);
    const logs: CommunicationLogEntry[] = existing ? JSON.parse(existing) : [];

    logs.push(entry);

    // Keep only the most recent logs
    if (logs.length > config.maxStoredLogs) {
      logs.splice(0, logs.length - config.maxStoredLogs);
    }

    localStorage.setItem(STORAGE_KEY, JSON.stringify(logs));
  } catch (error) {
    // Silently fail if storage is not available or full
    console.warn('Failed to store communication log:', error);
  }
}

/**
 * Get stored log entries
 */
export function getStoredLogs(): CommunicationLogEntry[] {
  if (!config.enableStorage) return [];

  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return stored ? JSON.parse(stored) : [];
  } catch (error) {
    console.warn('Failed to retrieve stored logs:', error);
    return [];
  }
}

/**
 * Clear stored log entries
 */
export function clearStoredLogs(): void {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch (error) {
    console.warn('Failed to clear stored logs:', error);
  }
}

/**
 * Log a communication event
 */
export function logCommunication(
  direction: 'inbound' | 'outbound',
  messageType: string,
  payload: any,
  options: {
    resource?: string;
    correlationId?: string;
    latencyMs?: number;
    error?: string;
    extra?: Record<string, any>;
  } = {}
): void {
  if (!config.enableLogging) return;

  const entry: CommunicationLogEntry = {
    timestamp: new Date().toISOString(),
    service: 'frontend',
    direction,
    protocol: 'websocket',
    message_type: messageType,
    target: 'backend',
    payload_summary: getPayloadSummary(payload),
    ...options.extra
  };

  if (options.resource) entry.resource = options.resource;
  if (options.correlationId) entry.correlation_id = options.correlationId;
  if (options.latencyMs !== undefined) entry.latency_ms = options.latencyMs;
  if (options.error) entry.error = options.error;

  // Log to console with structured format
  const logLevel = options.error ? 'error' : 'info';
  console[logLevel](`[Communication:${direction.toUpperCase()}]`, {
    type: messageType,
    resource: options.resource,
    correlationId: options.correlationId,
    payload: entry.payload_summary.payload,
    latencyMs: options.latencyMs,
    error: options.error
  });

  // Store in browser storage
  storeLogEntry(entry);
}

/**
 * Log WebSocket message
 */
export function logWebSocketMessage(
  direction: 'inbound' | 'outbound',
  messageType: string,
  payload: any,
  options: {
    resource?: string;
    correlationId?: string;
  } = {}
): void {
  logCommunication(direction, messageType, payload, {
    resource: options.resource,
    correlationId: options.correlationId
  });
}

/**
 * Log command request
 */
export function logCommandRequest(
  command: string,
  parameters: any,
  requestId: string
): void {
  logCommunication('outbound', 'command', parameters, {
    resource: command,
    correlationId: requestId
  });
}

/**
 * Log command response
 */
export function logCommandResponse(
  command: string,
  response: any,
  requestId: string,
  latencyMs?: number,
  error?: string
): void {
  logCommunication('inbound', 'response', response, {
    resource: command,
    correlationId: requestId,
    latencyMs,
    error
  });
}

/**
 * Log subscription event
 */
export function logSubscription(channels: string[]): void {
  logCommunication('outbound', 'subscription', { channels }, {
    extra: { channels }
  });
}

/**
 * Generate correlation ID
 */
export function generateCorrelationId(prefix: string = 'frontend'): string {
  return `${prefix}_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
}

/**
 * Extract correlation ID from message
 */
export function extractCorrelationId(message: any): string | undefined {
  return message?.correlation_id || message?.request_id;
}

/**
 * Utility to measure latency
 */
export class LatencyTimer {
  private startTime: number;
  private requestId: string;

  constructor(requestId: string) {
    this.startTime = performance.now();
    this.requestId = requestId;
  }

  getElapsedMs(): number {
    return performance.now() - this.startTime;
  }

  end(): number {
    return this.getElapsedMs();
  }
}

// Export types for use in other files
export type { CommunicationLogEntry, LogConfig };