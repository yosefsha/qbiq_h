/**
 * The `DataSource` the TypeORM CLI runs migrations against.
 *
 * `migrate_js` invokes `typeorm migration:run -d dist/data-source.js`, so this
 * file is the migration entry point and nothing else imports it. It reads the
 * same `DATABASE_URL` the application does, via `dataSourceOptions`.
 */

import 'reflect-metadata'
import { DataSource } from 'typeorm'

import { dataSourceOptions } from './db/data-source-options'

export default new DataSource(dataSourceOptions())
