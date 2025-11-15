const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

class ApiClient {
  private baseUrl: string

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl
  }

  private async request<T>(endpoint: string, options?: RequestInit): Promise<T> {
    const url = `${this.baseUrl}${endpoint}`
    const response = await fetch(url, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...options?.headers,
      },
    })

    if (!response.ok) {
      throw new Error(`API request failed: ${response.statusText}`)
    }

    return response.json()
  }

  async getHealth() {
    return this.request<any>('/api/v1/health')
  }

  async getPrediction(symbol: string = 'BTCUSD') {
    return this.request<any>('/api/v1/predict', {
      method: 'POST',
      body: JSON.stringify({ symbol }),
    })
  }

  async getPortfolioSummary() {
    return this.request<any>('/api/v1/portfolio/summary')
  }

  async getPositions() {
    return this.request<any[]>('/api/v1/portfolio/positions')
  }

  async getTrades() {
    return this.request<any[]>('/api/v1/portfolio/trades')
  }

  async getAgentStatus() {
    return this.request<any>('/api/v1/admin/agent/status')
  }
}

export const apiClient = new ApiClient(API_URL)

