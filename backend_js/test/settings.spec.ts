/**
 * Every environment-parsing rule the two services share.
 *
 * `settingsFromEnv` takes its environment as an argument precisely so this can
 * be tested without mutating `process.env` and hoping nothing else reads it
 * mid-run.
 */

import {
  DEFAULT_DATABASE_URL,
  DEFAULT_REDIS_URL,
  settingsFromEnv,
} from '../src/config/settings'

describe('settings', () => {
  it('boots with nothing configured at all', () => {
    const settings = settingsFromEnv({})

    expect(settings.databaseUrl).toBe(DEFAULT_DATABASE_URL)
    expect(settings.redisUrl).toBe(DEFAULT_REDIS_URL)
    expect(settings.cookieSecure).toBe(false)
    expect(settings.allowedOrigins).toEqual(['http://localhost:5173'])
    expect(settings.cacheTtlSeconds).toBe(300)
    expect(settings.sessionTtlSeconds).toBe(1800)
    expect(settings.logLevel).toBe('INFO')
  })

  it('prefers a whole URL over the component parts', () => {
    const settings = settingsFromEnv({
      DATABASE_URL: 'postgresql://a:b@explicit:5432/db',
      DB_HOST: 'ignored',
      DB_NAME: 'ignored',
      DB_USERNAME: 'ignored',
      DB_PASSWORD: 'ignored',
      REDIS_URL: 'redis://explicit:6379/4',
      REDIS_HOST: 'ignored',
    })

    expect(settings.databaseUrl).toBe('postgresql://a:b@explicit:5432/db')
    expect(settings.redisUrl).toBe('redis://explicit:6379/4')
  })

  it('composes a database URL from the components, defaulting the port', () => {
    const settings = settingsFromEnv({
      DB_HOST: 'db.internal',
      DB_NAME: 'qbiq_h_js',
      DB_USERNAME: 'app',
      DB_PASSWORD: 'secret',
    })

    expect(settings.databaseUrl).toBe('postgresql://app:secret@db.internal:5432/qbiq_h_js')
  })

  it('percent-encodes credentials that would otherwise break the URL', () => {
    const settings = settingsFromEnv({
      DB_HOST: 'db.internal',
      DB_NAME: 'qbiq_h_js',
      DB_USERNAME: 'user@corp',
      DB_PASSWORD: 'p/a:s@s#word',
    })

    // The `@` in the password must not end the userinfo early — otherwise the
    // tail of the password is read as the host and the app connects to
    // something that is not the database.
    expect(settings.databaseUrl).toBe(
      'postgresql://user%40corp:p%2Fa%3As%40s%23word@db.internal:5432/qbiq_h_js',
    )
    expect(new URL(settings.databaseUrl).hostname).toBe('db.internal')
  })

  it('refuses to fall back to localhost when the component set is partial', () => {
    expect(() =>
      settingsFromEnv({ DB_HOST: 'db.internal', DB_USERNAME: 'app' }),
    ).toThrow(/DB_NAME, DB_PASSWORD are missing/)
  })

  it('treats a blank value as unset, since ECS renders one for an unresolved variable', () => {
    const settings = settingsFromEnv({
      DATABASE_URL: '   ',
      DB_HOST: 'db.internal',
      DB_NAME: 'qbiq_h_js',
      DB_USERNAME: 'app',
      DB_PASSWORD: 'secret',
    })

    expect(settings.databaseUrl).toBe('postgresql://app:secret@db.internal:5432/qbiq_h_js')
  })

  it('selects the rediss scheme and carries the auth token in the password position', () => {
    const settings = settingsFromEnv({
      REDIS_HOST: 'cache.internal',
      REDIS_TLS: 'TRUE',
      REDIS_AUTH_TOKEN: 'to/ken',
      REDIS_DB: '2',
    })

    expect(settings.redisUrl).toBe('rediss://:to%2Fken@cache.internal:6379/2')
  })

  it.each([
    ['1', true],
    ['true', true],
    ['YES', true],
    [' on ', true],
    ['0', false],
    ['false', false],
    ['', false],
    ['maybe', false],
  ])('parses COOKIE_SECURE=%p as %p', (value, expected) => {
    expect(settingsFromEnv({ COOKIE_SECURE: value }).cookieSecure).toBe(expected)
  })

  it('splits and trims the allowed origins', () => {
    const settings = settingsFromEnv({
      ALLOWED_ORIGINS: 'http://localhost, http://localhost:8080 ,',
    })

    expect(settings.allowedOrigins).toEqual(['http://localhost', 'http://localhost:8080'])
  })

  it('rejects a wildcard origin, which credentialed CORS forbids (ADR-001)', () => {
    expect(() => settingsFromEnv({ ALLOWED_ORIGINS: '*' })).toThrow(/wildcard/)
  })

  it('rejects an empty origin list rather than serving no origin at all', () => {
    expect(() => settingsFromEnv({ ALLOWED_ORIGINS: ' , ' })).toThrow(/at least one origin/)
  })

  describe('TTL parsing', () => {
    it.each(['CACHE_TTL_SECONDS', 'SESSION_TTL_SECONDS'])(
      '%s defaults when unset',
      (name) => {
        const defaults = { CACHE_TTL_SECONDS: 300, SESSION_TTL_SECONDS: 1800 }
        const settings = settingsFromEnv({}) as unknown as Record<string, number>
        const field = name === 'CACHE_TTL_SECONDS' ? 'cacheTtlSeconds' : 'sessionTtlSeconds'
        expect(settings[field]).toBe(defaults[name as keyof typeof defaults])
      },
    )

    it('accepts a whole number of seconds, trimmed', () => {
      const settings = settingsFromEnv({
        CACHE_TTL_SECONDS: ' 600 ',
        SESSION_TTL_SECONDS: '7200',
      })

      expect(settings.cacheTtlSeconds).toBe(600)
      expect(settings.sessionTtlSeconds).toBe(7200)
    })

    it('treats a blank value as unset, as it does everywhere else', () => {
      // ECS renders an unresolved variable as "", which must not be fatal.
      expect(settingsFromEnv({ CACHE_TTL_SECONDS: '   ' }).cacheTtlSeconds).toBe(300)
    })

    // The bug this guards against: `Number.parseInt('5m')` is 5, so a mistyped
    // duration became a five-second session with nothing in the log to say so.
    it.each([
      ['5m', 'a unit suffix — the one that silently became 5 seconds'],
      ['abc', 'not a number at all'],
      ['3.5', 'a fraction'],
      ['1e3', 'exponent notation'],
      ['300s', 'a trailing unit'],
      ['0', 'zero, which Redis refuses as EX 0'],
      ['-60', 'a negative duration'],
      ['NaN', 'literally NaN'],
    ])('rejects SESSION_TTL_SECONDS=%p (%s)', (value) => {
      expect(() => settingsFromEnv({ SESSION_TTL_SECONDS: value })).toThrow(
        /SESSION_TTL_SECONDS must be a/,
      )
    })

    it('rejects a bad CACHE_TTL_SECONDS too, and names it', () => {
      expect(() => settingsFromEnv({ CACHE_TTL_SECONDS: 'abc' })).toThrow(
        /CACHE_TTL_SECONDS must be a whole number of seconds, got "abc"/,
      )
    })

    it('fails at startup rather than degrading, like a partial DB_* set does', () => {
      // The whole point: a configuration mistake stops the process. Previously
      // `CACHE_TTL_SECONDS=abc` produced NaN, reached Redis as `EX NaN`, and
      // was swallowed by the cache's own error handling — so the service ran
      // permanently uncached while reporting itself healthy.
      expect(() => settingsFromEnv({ CACHE_TTL_SECONDS: 'abc' })).toThrow(Error)
    })
  })

  it('is frozen, so nothing can reconfigure the process at runtime', () => {
    const settings = settingsFromEnv({})
    expect(Object.isFrozen(settings)).toBe(true)
  })
})
