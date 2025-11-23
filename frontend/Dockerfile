# syntax=docker/dockerfile:1.7

# Stage 1: Dependencies
FROM node:20-bullseye-slim AS deps
WORKDIR /app
COPY package*.json ./
RUN npm ci --only=production && npm cache clean --force

# Stage 2: Builder
FROM node:20-bullseye-slim AS builder
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1

# Copy package files
COPY package*.json ./

# Install all dependencies (including devDependencies for build)
RUN npm ci && npm cache clean --force

# Copy source code
COPY . ./

# Build Next.js application
RUN npm run build

# Stage 3: Runtime
FROM node:20-bullseye-slim AS runner
WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME="0.0.0.0"

# Create non-root user
RUN groupadd -r frontend && useradd -r -g frontend frontend && \
    mkdir -p /app /logs && \
    chown -R frontend:frontend /app /logs

# Copy production dependencies from deps stage
COPY --from=deps --chown=frontend:frontend /app/node_modules ./node_modules

# Copy built application from builder stage
COPY --from=builder --chown=frontend:frontend /app/.next ./.next
COPY --from=builder --chown=frontend:frontend /app/package*.json ./
# Copy public directory from builder if it exists (Next.js may create it during build)
COPY --from=builder --chown=frontend:frontend /app/public ./public

# Switch to non-root user
USER frontend

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD node -e "require('http').get('http://localhost:3000', (r) => {process.exit(r.statusCode < 500 ? 0 : 1)})" || exit 1

CMD ["npm", "run", "start"]

