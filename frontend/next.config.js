/** @type {import('next').NextConfig} */
const fs = require('fs')
const path = require('path')

const LOGO_FILENAME = 'logo.png'

function loadRootEnv() {
  const rootEnvPath = path.resolve(__dirname, '..', '.env')
  if (!fs.existsSync(rootEnvPath)) {
    return
  }

  const lines = fs.readFileSync(rootEnvPath, 'utf-8').split(/\r?\n/)
  lines.forEach((rawLine) => {
    const line = rawLine.trim()
    if (!line || line.startsWith('#') || !line.includes('=')) {
      return
    }
    const [rawKey, ...rawValueParts] = line.split('=')
    const key = rawKey.trim()
    if (!key || process.env[key] !== undefined) {
      return
    }
    const value = rawValueParts.join('=').trim().replace(/^['"]|['"]$/g, '')
    process.env[key] = value

    if (key === 'DELTA_API_KEY') {
      process.env.DELTA_EXCHANGE_API_KEY ||= value
    } else if (key === 'DELTA_API_SECRET') {
      process.env.DELTA_EXCHANGE_API_SECRET ||= value
    } else if (key === 'DELTA_API_URL') {
      process.env.DELTA_EXCHANGE_BASE_URL ||= value
    } else if (key === 'API_KEY' || key === 'BACKEND_API_KEY') {
      // Map backend API_KEY to frontend NEXT_PUBLIC_BACKEND_API_KEY
      // Only set if not already set (to allow explicit override)
      if (!process.env.NEXT_PUBLIC_BACKEND_API_KEY) {
        process.env.NEXT_PUBLIC_BACKEND_API_KEY = value
        console.log(`[next.config.js] Mapped ${key} to NEXT_PUBLIC_BACKEND_API_KEY (prefix: ${value.substring(0, 8)}...)`)
      }
    }
  })
}

function ensurePublicLogoAsset() {
  const sourcePath = path.resolve(__dirname, '..', LOGO_FILENAME)
  const destinationPath = path.resolve(__dirname, 'public', LOGO_FILENAME)

  try {
    if (!fs.existsSync(sourcePath)) {
      console.warn(`[next.config.js] Logo asset not found at ${sourcePath}`)
      return
    }

    const destinationDir = path.dirname(destinationPath)
    if (!fs.existsSync(destinationDir)) {
      fs.mkdirSync(destinationDir, { recursive: true })
    }

    const shouldCopy =
      !fs.existsSync(destinationPath) ||
      fs.statSync(destinationPath).mtimeMs < fs.statSync(sourcePath).mtimeMs

    if (!shouldCopy) {
      return
    }

    fs.copyFileSync(sourcePath, destinationPath)
    console.log('[next.config.js] Copied logo asset into frontend/public')
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    console.warn(`[next.config.js] Failed to sync logo asset: ${message}`)
  }
}

loadRootEnv()
ensurePublicLogoAsset()

const nextConfig = {
  reactStrictMode: true,
  typescript: {
    // !! WARN !!
    // Dangerously allow production builds to successfully complete even if
    // your project has type errors.
    // !! WARN !!
    ignoreBuildErrors: true,
  },
  eslint: {
    // Warning: This allows production builds to successfully complete even if
    // your project has ESLint errors.
    ignoreDuringBuilds: true,
  },
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000',
    NEXT_PUBLIC_WS_URL: process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000/ws',
    // Expose API key from root .env (API_KEY or BACKEND_API_KEY) as NEXT_PUBLIC_BACKEND_API_KEY
    NEXT_PUBLIC_BACKEND_API_KEY: process.env.NEXT_PUBLIC_BACKEND_API_KEY || process.env.API_KEY || process.env.BACKEND_API_KEY || 'dev-api-key',
  },
  webpack: (config, { isServer }) => {
    // Fix for paths with special characters on Windows
    // Normalize paths to remove any hash characters that might be incorrectly appended
    const originalResolve = config.resolve.resolve || config.resolve
    config.resolve = {
      ...config.resolve,
      modules: [path.resolve(__dirname, 'node_modules'), 'node_modules'],
      symlinks: false,
    }
    
    // Add a plugin to sanitize paths with hash characters
    config.plugins = config.plugins || []
    config.plugins.push({
      apply: (compiler) => {
        compiler.hooks.normalModuleFactory.tap('PathSanitizer', (nmf) => {
          nmf.hooks.beforeResolve.tap('PathSanitizer', (resolveData) => {
            if (resolveData.request && resolveData.request.includes('#')) {
              // Remove hash from the end of the request path if it's incorrectly appended
              resolveData.request = resolveData.request.replace(/\.(js|ts|tsx|jsx)#$/g, '.$1')
              // Also clean the context if it has hash issues
              if (resolveData.context && resolveData.context.includes('#2')) {
                resolveData.context = resolveData.context.replace(/#2/g, '-2')
              }
            }
          })
        })
      },
    })
    
    return config
  },
  // Disable output file tracing to avoid path resolution issues
  experimental: {
    outputFileTracingExcludes: {
      '*': [
        '**/@swc/**',
        '**/@next/**',
      ],
    },
  },
}

module.exports = nextConfig

