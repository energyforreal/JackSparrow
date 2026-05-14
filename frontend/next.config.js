/** @type {import('next').NextConfig} */
const fs = require('fs')
const path = require('path')

const LOGO_FILENAME = 'logo.png'

// Env-file split (matches agent/backend Pydantic loaders):
//   - .env.example (committed): non-secret defaults / thresholds / public URLs.
//   - .env          (gitignored): secrets only.
// Load order: .env.example first, then .env on top.
// Real process.env values (CI / Docker / shell exports) always win over either file.
function applyEnvFile(filePath, externalKeys, { trustOverFiles }) {
  if (!fs.existsSync(filePath)) {
    return
  }

  const seenInThisFile = new Set()
  const lines = fs.readFileSync(filePath, 'utf-8').split(/\r?\n/)
  lines.forEach((rawLine) => {
    const line = rawLine.trim()
    if (!line || line.startsWith('#') || !line.includes('=')) {
      return
    }
    const [rawKey, ...rawValueParts] = line.split('=')
    const key = rawKey.trim()
    if (!key) {
      return
    }
    const value = rawValueParts.join('=').trim().replace(/^['"]|['"]$/g, '')

    // Skip keys already provided by the real environment (shell/CI/Docker).
    if (externalKeys.has(key)) {
      return
    }

    // Within this file pass, allow override of values written by earlier file(s).
    // First time we touch this key in this load order, write it.
    if (!seenInThisFile.has(key) || trustOverFiles) {
      process.env[key] = value
      seenInThisFile.add(key)
    }

    if (key === 'DELTA_API_KEY' && !externalKeys.has('DELTA_EXCHANGE_API_KEY')) {
      process.env.DELTA_EXCHANGE_API_KEY = value
    } else if (key === 'DELTA_API_SECRET' && !externalKeys.has('DELTA_EXCHANGE_API_SECRET')) {
      process.env.DELTA_EXCHANGE_API_SECRET = value
    } else if (key === 'DELTA_API_URL' && !externalKeys.has('DELTA_EXCHANGE_BASE_URL')) {
      process.env.DELTA_EXCHANGE_BASE_URL = value
    }
  })
}

function loadRootEnv() {
  const rootDir = path.resolve(__dirname, '..')
  // Snapshot external env so file values never clobber shell/CI/Docker exports.
  const externalKeys = new Set(Object.keys(process.env))
  applyEnvFile(path.join(rootDir, '.env.example'), externalKeys, { trustOverFiles: false })
  applyEnvFile(path.join(rootDir, '.env'), externalKeys, { trustOverFiles: true })
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
    NEXT_PUBLIC_BACKEND_PROXY_BASE: process.env.NEXT_PUBLIC_BACKEND_PROXY_BASE || '/api/backend',
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

