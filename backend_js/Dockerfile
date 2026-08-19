# syntax=docker/dockerfile:1

# Build stage: install every dependency (dev included) and compile TypeScript.
FROM node:22-alpine AS builder

WORKDIR /build

# Copy manifests first so dependency installation caches independently of
# source.
COPY package.json package-lock.json ./
RUN npm ci

COPY tsconfig.json tsconfig.build.json nest-cli.json ./
COPY src ./src
RUN npm run build


# Dependency stage: the runtime dependency tree alone, so the final image
# carries no compiler, no test runner and no linter.
FROM node:22-alpine AS deps

WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci --omit=dev && npm cache clean --force


# Runtime stage.
FROM node:22-alpine AS runtime

ENV NODE_ENV=production

WORKDIR /srv

COPY --from=deps /build/node_modules ./node_modules
COPY --from=builder /build/dist ./dist
COPY package.json ./

# Migrations ship in the runtime image deliberately. `typeorm migration:run`
# runs from this same image — as the `migrate_js` service locally, and as a
# one-off task before a rolling deploy — so the schema is always migrated by
# the exact build being deployed, never by whatever version a developer's
# laptop happens to have checked out. `dist/data-source.js` is the CLI's entry
# point and reads the same DATABASE_URL the application does.

# Run as an unprivileged user; nothing here needs root. The node image already
# ships a `node` user with uid 1000.
USER node
EXPOSE 8000

CMD ["node", "dist/main.js"]
