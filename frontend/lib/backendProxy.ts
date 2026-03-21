/**
 * Same-origin path for the FastAPI backend via the Next.js Route Handler proxy
 * (`/api/backend/*` → BACKEND_INTERNAL_URL with server-only X-API-Key).
 */
export function getBackendProxyBase(): string {
  return process.env.NEXT_PUBLIC_BACKEND_PROXY_BASE || '/api/backend'
}
