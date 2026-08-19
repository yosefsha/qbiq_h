/**
 * Connects the integration tests to a real Postgres.
 *
 * The repository and seeder tests assert things only a real database can
 * answer — `ILIKE` escaping, index-backed ordering, the check constraints — so
 * they are integration tests by nature. Whether a server is there is decided
 * once in `global-setup.ts`; this module only reads the answer, which is what
 * lets a whole suite be reported as *skipped* rather than passing without
 * having tested anything.
 *
 * `TEST_DATABASE_URL` points at a database these tests may drop and rebuild
 * the schema in. It defaults to a `_test` database, so it can never touch the
 * one the running stack is serving from.
 */

import { DataSource } from 'typeorm'

import { ENTITIES } from '../src/db/data-source-options'
import { POSTGRES_FLAG } from './global-setup'

export const TEST_DATABASE_URL =
  process.env.TEST_DATABASE_URL ?? 'postgresql://qbiq:qbiq@localhost:5432/qbiq_h_js_test'

/** True when `global-setup.ts` found a reachable test database. */
export const POSTGRES_AVAILABLE = process.env[POSTGRES_FLAG] === '1'

/** `describe`, or `describe.skip` when there is nothing to connect to. */
export const describeWithPostgres = POSTGRES_AVAILABLE ? describe : describe.skip

export interface TestDatabase {
  require: () => DataSource
}

/**
 * Registers the connect/disconnect lifecycle for the calling `describe`.
 *
 * The schema is built with `synchronize` rather than by running the migration:
 * these suites are about behaviour against a real database, and
 * `migration.spec.ts` is where the migration itself is checked.
 */
export function useTestDatabase(options: { synchronize?: boolean } = {}): TestDatabase {
  let dataSource: DataSource | null = null

  beforeAll(async () => {
    dataSource = await new DataSource({
      type: 'postgres',
      url: TEST_DATABASE_URL,
      entities: ENTITIES,
      synchronize: options.synchronize ?? true,
      dropSchema: true,
      logging: false,
      connectTimeoutMS: 2_000,
    }).initialize()
  })

  afterAll(async () => {
    if (dataSource?.isInitialized) {
      await dataSource.destroy()
    }
  })

  return {
    require: () => {
      if (dataSource === null) {
        throw new Error('test database not initialised')
      }
      return dataSource
    },
  }
}
