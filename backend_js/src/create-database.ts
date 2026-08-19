/**
 * Creates this service's database if it does not already exist.
 *
 * The Postgres container creates exactly one database, the Python service's.
 * This one owns `qbiq_h_js` — a separate database on the same server, so the
 * two implementations keep separate migration ledgers over what is
 * deliberately the same schema, and neither can half-migrate the other's.
 *
 * `CREATE DATABASE` cannot run inside a transaction and has no `IF NOT
 * EXISTS`, so existence is checked first and the race is tolerated: two
 * concurrent runs, one loses with `42P04 duplicate_database`, which is the
 * outcome we wanted anyway.
 *
 * Run from `migrate_js` before the migration, and idempotent, so it is safe on
 * every start.
 */

import { Client } from 'pg'

import { JsonLogger } from './common/logging/json-logger'
import { settings } from './config/settings'

const logger = new JsonLogger('app.create-database')

/** Postgres' error code for "database already exists". */
const DUPLICATE_DATABASE = '42P04'

/**
 * Returns the database name from a connection URL, and the URL to connect to
 * in order to create it.
 *
 * `ADMIN_DATABASE_URL` names a database that already exists — you cannot
 * connect to the one you are about to create. It defaults to the built-in
 * `postgres` maintenance database on the same server, which is present on
 * every Postgres installation.
 */
function targets(): { adminUrl: string; databaseName: string } {
  const target = new URL(settings.databaseUrl)
  const databaseName = decodeURIComponent(target.pathname.replace(/^\//, ''))
  if (databaseName === '') {
    throw new Error('DATABASE_URL names no database, so there is nothing to create.')
  }

  const admin = process.env.ADMIN_DATABASE_URL?.trim()
  if (admin) {
    return { adminUrl: admin, databaseName }
  }

  const fallback = new URL(settings.databaseUrl)
  fallback.pathname = '/postgres'
  return { adminUrl: fallback.toString(), databaseName }
}

export async function createDatabase(): Promise<void> {
  const { adminUrl, databaseName } = targets()
  const client = new Client({ connectionString: adminUrl })
  await client.connect()
  try {
    const existing = await client.query('SELECT 1 FROM pg_database WHERE datname = $1', [
      databaseName,
    ])
    if (existing.rowCount !== 0) {
      logger.log('database already exists', { database: databaseName })
      return
    }
    // The name is an identifier, not a value, so it cannot be a bound
    // parameter. It comes from this service's own DATABASE_URL rather than
    // from a request, and the quotes are doubled so a name containing one
    // cannot end the identifier early.
    await client.query(`CREATE DATABASE "${databaseName.replace(/"/g, '""')}"`)
    logger.log('database created', { database: databaseName })
  } catch (cause) {
    if ((cause as { code?: string }).code === DUPLICATE_DATABASE) {
      logger.log('database created concurrently by another run', {
        database: databaseName,
      })
      return
    }
    throw cause
  } finally {
    await client.end()
  }
}

if (require.main === module) {
  createDatabase().catch((cause: unknown) => {
    logger.exception('failed to create database', cause)
    process.exitCode = 1
  })
}
