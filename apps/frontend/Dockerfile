# syntax=docker/dockerfile:1.7

############################
# 1) Dependencies (cached)
############################
FROM oven/bun:1.3.2-alpine AS deps
WORKDIR /app

# Only copy what is needed to install deps (best layer caching)
COPY package.json bun.lock ./

# Install all deps (including devDeps) for build
RUN bun install --frozen-lockfile

############################
# 2) Build
############################
FROM oven/bun:1.3.2-alpine AS build
WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
COPY . .

ENV NODE_ENV=production

# Build client + SSR output into dist/
RUN bun --bun vite build

############################
# 3) Production runtime
############################
FROM oven/bun:1.3.2-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV PORT=3000

# Install only production deps for runtime (smaller image)
COPY package.json bun.lock ./
RUN rm -rf node_modules ~/.bun/install/cache && \
    bun install --production --no-verify

# Copy the built artifacts + your custom production server
COPY --from=build /app/dist ./dist
COPY --from=build /app/public ./public
COPY --from=build /app/server.ts ./server.ts

# Optional: if you rely on Lingui runtime message TS files at runtime (usually bundled),
# you can also copy locales. Keeping it minimal by default.
# COPY --from=build /app/src/locales ./src/locales

EXPOSE 3000

# Your server.ts expects dist/server/server.js and dist/client
CMD ["bun", "run", "server.ts"]