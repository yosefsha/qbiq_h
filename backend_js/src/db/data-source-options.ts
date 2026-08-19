/**
 * The single description of how this service talks to Postgres.
 *
 * Shared by the Nest application (`TypeOrmModule.forRoot`), the migration CLI
 * (`data-source.ts`), and the seeder, so all three connect identically and a
 * change to pooling or SSL cannot apply to only one of them.
 *
 * `synchronize` is false everywhere and always: the schema is owned by the
 * migration in `src/migrations`, which runs from the same image as the code
 * that queries it. A schema quietly reshaped at boot is exactly the drift the
 * `migrate_js` service exists to make impossible.
 */

import { DataSourceOptions } from 'typeorm'

import { CategoryEntity } from './entities/category.entity'
import { ProductEntity } from './entities/product.entity'
import { ReviewEntity } from './entities/review.entity'
import { settings } from '../config/settings'

export const ENTITIES = [CategoryEntity, ProductEntity, ReviewEntity]

export function dataSourceOptions(url: string = settings.databaseUrl): DataSourceOptions {
  return {
    type: 'postgres',
    url,
    entities: ENTITIES,
    // Compiled alongside everything else, so the CLI finds `.js` at runtime
    // and ts-jest finds `.ts` in the tests.
    migrations: [`${__dirname}/../migrations/*.{ts,js}`],
    migrationsTableName: 'typeorm_migrations',
    synchronize: false,
    logging: false,
  }
}
