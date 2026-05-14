/** Maximum `schema_version` from backend the UI is validated against. */
export const WS_SCHEMA_VERSION_SUPPORTED_MAX = 1

let warnedSchemaMismatch = false

/** Log once in development if backend schema_version exceeds what we tested against. */
export function warnIfWebSocketSchemaUnsupported(version: unknown): void {
  if (process.env.NODE_ENV !== 'development') return
  if (version == null || typeof version !== 'number') return
  if (version <= WS_SCHEMA_VERSION_SUPPORTED_MAX) return
  if (warnedSchemaMismatch) return
  warnedSchemaMismatch = true
  if (typeof console !== 'undefined' && typeof console.warn === 'function') {
    console.warn(
      '[WebSocket] schema_version',
      version,
      'exceeds supported max',
      WS_SCHEMA_VERSION_SUPPORTED_MAX,
      '— update client parsers if needed.'
    )
  }
}
