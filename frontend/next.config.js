/** @type {import('next').NextConfig} */
const fs = require('fs')
const path = require('path')

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
    }
  })
}

loadRootEnv()

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

