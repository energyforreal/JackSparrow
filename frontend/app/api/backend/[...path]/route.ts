import { NextRequest, NextResponse } from 'next/server'

export const dynamic = 'force-dynamic'

const HOP_BY_HOP = new Set([
  'connection',
  'keep-alive',
  'proxy-authenticate',
  'proxy-authorization',
  'te',
  'trailers',
  'transfer-encoding',
  'upgrade',
  'host',
])

function buildTargetUrl(req: NextRequest, pathSegments: string[]): string {
  const base = (process.env.BACKEND_INTERNAL_URL || 'http://127.0.0.1:8000').replace(/\/$/, '')
  const path = pathSegments.length ? `/${pathSegments.join('/')}` : ''
  return `${base}${path}${req.nextUrl.search}`
}

async function proxy(req: NextRequest, pathSegments: string[]): Promise<Response> {
  const url = buildTargetUrl(req, pathSegments)
  const apiKey = process.env.BACKEND_API_KEY || ''

  const headers = new Headers()
  req.headers.forEach((value, name) => {
    const lower = name.toLowerCase()
    if (HOP_BY_HOP.has(lower)) {
      return
    }
    headers.set(name, value)
  })
  if (apiKey) {
    headers.set('X-API-Key', apiKey)
  }

  const init: RequestInit = {
    method: req.method,
    headers,
    redirect: 'manual',
  }

  if (req.method !== 'GET' && req.method !== 'HEAD') {
    init.body = await req.arrayBuffer()
  }

  const res = await fetch(url, init)
  const out = new NextResponse(res.body, {
    status: res.status,
    statusText: res.statusText,
  })

  res.headers.forEach((value, key) => {
    const lower = key.toLowerCase()
    if (lower === 'transfer-encoding') {
      return
    }
    out.headers.set(key, value)
  })

  return out
}

type RouteParams = { params: { path: string[] } }

export async function GET(req: NextRequest, { params }: RouteParams) {
  return proxy(req, params.path || [])
}

export async function POST(req: NextRequest, { params }: RouteParams) {
  return proxy(req, params.path || [])
}

export async function PUT(req: NextRequest, { params }: RouteParams) {
  return proxy(req, params.path || [])
}

export async function PATCH(req: NextRequest, { params }: RouteParams) {
  return proxy(req, params.path || [])
}

export async function DELETE(req: NextRequest, { params }: RouteParams) {
  return proxy(req, params.path || [])
}

export async function OPTIONS(req: NextRequest, { params }: RouteParams) {
  return proxy(req, params.path || [])
}
