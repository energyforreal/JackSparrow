// Get API URL from environment variable
// In production, NEXT_PUBLIC_API_URL must be set
// Fallback to localhost only in development
const API_URL =
  process.env.NEXT_PUBLIC_API_URL ||
  (process.env.NODE_ENV === 'development' ? 'http://localhost:8000' : '')

if (!API_URL && process.env.NODE_ENV === 'production') {
  console.error('NEXT_PUBLIC_API_URL environment variable is required in production')
}

const API_KEY = process.env.NEXT_PUBLIC_BACKEND_API_KEY

interface ApiError {
  error?: {
    code?: string
    message?: string
    details?: unknown
  }
  message?: string
}

class ApiClient {
  private baseUrl: string
  private defaultTimeout: number = 30000 // 30 seconds
  private maxRetries: number = 3
  private baseRetryDelay: number = 1000 // 1 second

  constructor(baseUrl: string) {
    if (!baseUrl) {
      throw new Error('API URL is not configured. Set NEXT_PUBLIC_API_URL environment variable.')
    }
    this.baseUrl = baseUrl
  }

  private calculateRetryDelay(attempt: number): number {
    // Exponential backoff: baseDelay * 2^attempt, capped at 10 seconds
    return Math.min(this.baseRetryDelay * Math.pow(2, attempt), 10000)
  }

  private async requestWithTimeout<T>(
    url: string,
    options: RequestInit,
    timeout: number
  ): Promise<Response> {
    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), timeout)

    try {
      const response = await fetch(url, {
        ...options,
        signal: controller.signal,
      })
      clearTimeout(timeoutId)
      return response
    } catch (error) {
      clearTimeout(timeoutId)
      if (error instanceof Error && error.name === 'AbortError') {
        throw new Error(`Request timeout after ${timeout}ms`)
      }
      throw error
    }
  }

  private async request<T>(
    endpoint: string,
    options?: RequestInit,
    timeout?: number,
    retryCount: number = 0
  ): Promise<T> {
    const url = `${this.baseUrl}${endpoint}`
    const requestTimeout = timeout ?? this.defaultTimeout
    
    try {
      const response = await this.requestWithTimeout(
        url,
        {
          ...options,
          headers: {
            'Content-Type': 'application/json',
            ...(API_KEY ? { 'X-API-Key': API_KEY } : {}),
            ...options?.headers,
          },
        },
        requestTimeout
      )

      if (!response.ok) {
        let errorMessage = `API request failed: ${response.statusText}`
        try {
          const errorData: ApiError = await response.json()
          errorMessage = errorData.error?.message || errorData.message || errorMessage
        } catch {
          // If response is not JSON, use status text
        }
        
        // Retry on server errors (5xx) but not on client errors (4xx)
        const isRetryable = response.status >= 500 && retryCount < this.maxRetries
        if (isRetryable) {
          const delay = this.calculateRetryDelay(retryCount)
          console.warn(
            `API request failed with status ${response.status}, retrying in ${delay}ms (attempt ${retryCount + 1}/${this.maxRetries})`
          )
          await new Promise((resolve) => setTimeout(resolve, delay))
          return this.request<T>(endpoint, options, timeout, retryCount + 1)
        }
        
        throw new Error(errorMessage)
      }

      return response.json()
    } catch (error) {
      // Retry on network errors and timeouts
      const isRetryable =
        (error instanceof Error &&
          (error.message.includes('timeout') ||
            error.message.includes('network') ||
            error.message.includes('fetch'))) &&
        retryCount < this.maxRetries

      if (isRetryable) {
        const delay = this.calculateRetryDelay(retryCount)
        console.warn(
          `API request failed: ${error instanceof Error ? error.message : 'Unknown error'}, retrying in ${delay}ms (attempt ${retryCount + 1}/${this.maxRetries})`
        )
        await new Promise((resolve) => setTimeout(resolve, delay))
        return this.request<T>(endpoint, options, timeout, retryCount + 1)
      }

      if (error instanceof Error) {
        // Provide user-friendly error messages
        if (error.message.includes('timeout')) {
          throw new Error('Request timed out. Please check your connection and try again.')
        }
        if (error.message.includes('fetch') || error.message.includes('network')) {
          throw new Error('Network error. Please check your connection and try again.')
        }
        throw error
      }
      throw new Error('Unknown error occurred during API request')
    }
  }

  async getHealth(): Promise<{
    status: string
    health_score: number
    services: Record<string, {
      status: string
      latency_ms?: number
      error?: string
      details?: Record<string, unknown>
    }>
    degradation_reasons?: string[]
    agent_state?: string
    timestamp?: string
  }> {
    return this.request<{
      status: string
      health_score: number
      services: Record<string, {
        status: string
        latency_ms?: number
        error?: string
        details?: Record<string, unknown>
      }>
      degradation_reasons?: string[]
      agent_state?: string
      timestamp?: string
    }>('/api/v1/health')
  }

  async getPrediction(symbol: string = 'BTCUSD'): Promise<{
    signal: string
    confidence: number
    position_size?: number
    reasoning_chain: unknown
    model_predictions: unknown[]
    timestamp: string
  }> {
    return this.request('/api/v1/predict', {
      method: 'POST',
      body: JSON.stringify({ symbol }),
    })
  }

  async getPortfolioSummary(): Promise<{
    total_value: number
    available_balance: number
    open_positions: number
    total_unrealized_pnl: number
    total_realized_pnl: number
    positions: unknown[]
  }> {
    return this.request('/api/v1/portfolio/summary')
  }

  async getPositions(): Promise<unknown[]> {
    return this.request<unknown[]>('/api/v1/portfolio/positions')
  }

  async getTrades(): Promise<unknown[]> {
    return this.request<unknown[]>('/api/v1/portfolio/trades')
  }

  async getAgentStatus(): Promise<{
    available: boolean
    state: string
    health?: unknown
    latency_ms?: number
  }> {
    return this.request('/api/v1/admin/agent/status')
  }

  async getSystemTime(): Promise<{
    server_time: string
    timestamp_ms: number
    timezone: string
  }> {
    return this.request('/api/v1/system/time')
  }
}

export const apiClient = new ApiClient(API_URL)

