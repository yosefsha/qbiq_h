/**
 * Decides, once, whether the integration tests have a Postgres to run against.
 *
 * Jest cannot make that decision inside a test file: `describe.skip` has to be
 * chosen when the file is loaded, and probing a server is asynchronous. So it
 * happens here, before any test file is imported, and the answer travels to
 * the workers in the environment.
 *
 * A skipped suite is reported as skipped rather than quietly passing — a
 * green run that never touched a database is the failure mode this exists to
 * avoid. CI brings Postgres up and fails on any skip.
 *
 * The test database is created if the server is reachable but the database is
 * not there, so `docker compose up postgres` is the whole setup.
 */

import { Client } from 'pg'

const TEST_DATABASE_URL =
  process.env.TEST_DATABASE_URL ?? 'postgresql://qbiq:qbiq@localhost:5432/qbiq_h_js_test'

export const POSTGRES_FLAG = 'QBIQ_TEST_POSTGRES'

async function canConnect(url: string): Promise<boolean> {
  const client = new Client({ connectionString: url, connectionTimeoutMillis: 2_000 })
  try {
    await client.connect()
    await client.end()
    return true
  } catch {
    return false
  }
}

async function createTestDatabase(): Promise<boolean> {
  const target = new URL(TEST_DATABASE_URL)
  const databaseName = decodeURIComponent(target.pathname.replace(/^\//, ''))
  const admin = new URL(TEST_DATABASE_URL)
  admin.pathname = '/postgres'

  const client = new Client({
    connectionString: admin.toString(),
    connectionTimeoutMillis: 2_000,
  })
  try {
    await client.connect()
  } catch {
    return false
  }
  try {
    await client.query(`CREATE DATABASE "${databaseName.replace(/"/g, '""')}"`)
    return true
  } catch {
    return false
  } finally {
    await client.end()
  }
}

export default async function globalSetup(): Promise<void> {
  let available = await canConnect(TEST_DATABASE_URL)
  if (!available) {
    available = (await createTestDatabase()) && (await canConnect(TEST_DATABASE_URL))
  }

  process.env[POSTGRES_FLAG] = available ? '1' : '0'
  if (!available) {
    console.warn(
      `\n  No Postgres at ${TEST_DATABASE_URL} — the integration suites will report as skipped.` +
        '\n  Bring one up with `docker compose up postgres`, or set TEST_DATABASE_URL.\n',
    )
  }
}
