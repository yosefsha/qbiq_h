# syntax=docker/dockerfile:1

# Build stage: type-check and bundle the SPA.
FROM node:22-alpine AS builder

WORKDIR /build

# Copy manifests first so dependency installation caches independently of source.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build


# Runtime stage: nginx serves the built assets and path-routes /api to the API,
# which is what keeps the SPA and API on one origin (see ADR-001).
FROM nginx:1.27-alpine AS runtime

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /build/dist /usr/share/nginx/html

EXPOSE 80
