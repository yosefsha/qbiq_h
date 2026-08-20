/**
 * Runtime configuration loaded from environment variables.
 *
 * A direct port of `backend/app/settings.py`, rule for rule, so both
 * implementations answer to exactly the same environment. Settings are built
 * once, at module load, so `node dist/main.js` boots with zero environment
 * variables set — every field has a local-development default.
 *
 * Two ways to point the app at its stores, in priority order:
 *
 * 1. **A whole URL** — `DATABASE_URL` / `REDIS_URL`. This is what Docker
 *    Compose and CI set, and it always wins.
 * 2. **The component parts** — `DB_HOST`/`DB_PORT`/`DB_NAME`/`DB_USERNAME`/
 *    `DB_PASSWORD` and `REDIS_HOST`/`REDIS_PORT`/`REDIS_TLS`/
 *    `REDIS_AUTH_TOKEN`, from which the URL is composed here.
 *
 * The second form exists because of ECS: the database password and the Redis
 * AUTH token are resolved by ECS as the task starts, so nothing at synth time
 * can assemble a URL out of them. Composing it is the application's job, and
 * it happens here rather than in a shell wrapper so that it is covered by
 * `settings.spec.ts`.
 *
 * Credentials are percent-encoded on the way in. A generated password
 * containing `/`, `@`, `#` or `:` otherwise produces a URL that parses
 * wrongly — `@` in particular ends the userinfo early and the tail of the
 * password is read as the host.
 */

const TRUE_VALUES = new Set(['1', 'true', 'yes', 'on'])

/**
 * What a laptop with no environment configured at all points at — the ports
 * docker-compose.yml publishes by default.
 */
export const DEFAULT_DATABASE_URL = 'postgresql://qbiq:qbiq@localhost:5432/qbiq_h'
export const DEFAULT_REDIS_URL = 'redis://localhost:6379/0'

const DEFAULT_DB_PORT = '5432'
const DEFAULT_REDIS_PORT = '6379'
const DEFAULT_REDIS_DB = '0'

export interface Settings {
  readonly databaseUrl: string
  readonly redisUrl: string
  readonly cookieSecure: boolean
  readonly allowedOrigins: readonly string[]
  readonly cacheTtlSeconds: number
  readonly sessionTtlSeconds: number
  readonly logLevel: string
}

/**
 * Parses a boolean environment variable value.
 *
 * Anything in `TRUE_VALUES` (case-insensitive, trimmed) is true; everything
 * else is false.
 */
function parseBool(value: string): boolean {
  return TRUE_VALUES.has(value.trim().toLowerCase())
}

/**
 * Parses a comma-separated list of CORS origins.
 *
 * A wildcard origin is rejected: credentialed CORS forbids one per ADR-001,
 * since browsers refuse `Access-Control-Allow-Origin: *` alongside
 * credentialed requests, which would silently break the session cookie.
 */
function parseOrigins(value: string): readonly string[] {
  const origins = value
    .split(',')
    .map((origin) => origin.trim())
    .filter((origin) => origin.length > 0)
  if (origins.length === 0) {
    throw new Error('ALLOWED_ORIGINS must contain at least one origin.')
  }
  if (origins.includes('*')) {
    throw new Error(
      "ALLOWED_ORIGINS may not contain a wildcard '*': credentialed CORS " +
        'forbids a wildcard origin (see ADR-001-server-owned-cart.md).',
    )
  }
  return Object.freeze(origins)
}

/**
 * Parses a duration in whole seconds, or throws.
 *
 * `Number.parseInt` is deliberately not used here. It never throws: it reads
 * as many leading digits as it finds and ignores the rest, so
 * `SESSION_TTL_SECONDS=5m` becomes `5` — a five-second session, carts
 * evaporating mid-shop, and nothing in the log saying why — and
 * `CACHE_TTL_SECONDS=abc` becomes `NaN`, which reaches Redis as `EX NaN` and
 * fails every cache write, silently, for the life of the process.
 *
 * Both are configuration mistakes, and a configuration mistake must stop the
 * process at startup rather than degrade it in a way that looks healthy. That
 * is the same rule `databaseUrl` already applies to a partial `DB_*` set.
 *
 * Non-positive values are rejected too: Redis refuses `EX 0` outright, so a
 * zero or negative TTL cannot do anything except fail later and further away.
 */
function parseDurationSeconds(name: string, value: string): number {
  const trimmed = value.trim()
  if (!/^\+?\d+$/.test(trimmed)) {
    throw new Error(
      `${name} must be a whole number of seconds, got ${JSON.stringify(value)}.`,
    )
  }

  const seconds = Number(trimmed)
  if (!Number.isSafeInteger(seconds) || seconds <= 0) {
    throw new Error(
      `${name} must be a positive whole number of seconds, got ${JSON.stringify(value)}.`,
    )
  }
  return seconds
}

/**
 * Returns a trimmed environment variable, treating blank as unset.
 *
 * ECS renders an unresolved value as an empty string rather than omitting the
 * variable, so `''` has to mean "not configured" or a blank `DATABASE_URL`
 * would win over a perfectly good set of components.
 */
function env(name: string, source: NodeJS.ProcessEnv): string | null {
  const value = source[name]
  if (value === undefined) {
    return null
  }
  const trimmed = value.trim()
  return trimmed === '' ? null : trimmed
}

/** Percent-encodes a URL component, leaving nothing — not even `/` — safe. */
function quote(value: string): string {
  return encodeURIComponent(value)
}

/**
 * Returns `DATABASE_URL`, or composes one from the `DB_*` components.
 *
 * `DB_HOST` is the marker for component-style configuration. If it is absent,
 * nothing was configured and the local default applies. If it is present, the
 * remaining components must be too: falling back to `localhost` because one
 * variable was forgotten is the exact failure this function exists to
 * prevent — the app would boot, `/health` would answer, and every query would
 * go to a database that is not there.
 */
function databaseUrl(source: NodeJS.ProcessEnv): string {
  const explicit = env('DATABASE_URL', source)
  if (explicit !== null) {
    return explicit
  }

  const host = env('DB_HOST', source)
  if (host === null) {
    return DEFAULT_DATABASE_URL
  }

  const rawName = env('DB_NAME', source)
  const rawUsername = env('DB_USERNAME', source)
  const rawPassword = env('DB_PASSWORD', source)
  const missing = (
    [
      ['DB_NAME', rawName],
      ['DB_USERNAME', rawUsername],
      ['DB_PASSWORD', rawPassword],
    ] as const
  )
    .filter(([, value]) => value === null)
    .map(([name]) => name)

  if (missing.length > 0) {
    throw new Error(
      'DB_HOST is set, so the database is configured from components, but ' +
        `${missing.join(', ')} ${missing.length === 1 ? 'is' : 'are'} missing. ` +
        'Set the missing variables, or set DATABASE_URL instead.',
    )
  }

  const port = env('DB_PORT', source) ?? DEFAULT_DB_PORT
  return `postgresql://${quote(rawUsername as string)}:${quote(rawPassword as string)}@${host}:${port}/${quote(rawName as string)}`
}

/**
 * Returns `REDIS_URL`, or composes one from the `REDIS_*` components.
 *
 * `REDIS_TLS` selects the scheme: ElastiCache with encryption in transit only
 * accepts a TLS connection, and `redis://` against it fails with a protocol
 * error rather than anything that names the real cause. `REDIS_AUTH_TOKEN`
 * goes in the password position with an empty username, which is how a Redis
 * `requirepass` credential is carried in a URL.
 */
function redisUrl(source: NodeJS.ProcessEnv): string {
  const explicit = env('REDIS_URL', source)
  if (explicit !== null) {
    return explicit
  }

  const host = env('REDIS_HOST', source)
  if (host === null) {
    return DEFAULT_REDIS_URL
  }

  const scheme = parseBool(env('REDIS_TLS', source) ?? '') ? 'rediss' : 'redis'
  const port = env('REDIS_PORT', source) ?? DEFAULT_REDIS_PORT
  const database = env('REDIS_DB', source) ?? DEFAULT_REDIS_DB

  const token = env('REDIS_AUTH_TOKEN', source)
  const credentials = token === null ? '' : `:${quote(token)}@`

  return `${scheme}://${credentials}${host}:${port}/${database}`
}

/** Builds `Settings` from environment variables with local defaults. */
export function settingsFromEnv(source: NodeJS.ProcessEnv = process.env): Settings {
  return Object.freeze({
    databaseUrl: databaseUrl(source),
    redisUrl: redisUrl(source),
    cookieSecure: parseBool(source.COOKIE_SECURE ?? 'false'),
    allowedOrigins: parseOrigins(source.ALLOWED_ORIGINS ?? 'http://localhost:5173'),
    cacheTtlSeconds: parseDurationSeconds(
      'CACHE_TTL_SECONDS',
      env('CACHE_TTL_SECONDS', source) ?? '300',
    ),
    sessionTtlSeconds: parseDurationSeconds(
      'SESSION_TTL_SECONDS',
      env('SESSION_TTL_SECONDS', source) ?? '1800',
    ),
    logLevel: (source.LOG_LEVEL ?? 'INFO').toUpperCase(),
  })
}

/** Immutable, process-wide application configuration. */
export const settings: Settings = settingsFromEnv()
