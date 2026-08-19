/**
 * The application's module graph.
 *
 * `TypeOrmModule.forRoot` is handed the same options object the migration CLI
 * and the seeder use, so all three connect identically — and `synchronize` is
 * false in it, because the schema is owned by the migration that `migrate_js`
 * runs from this same image.
 */

import { Module } from '@nestjs/common'
import { TypeOrmModule } from '@nestjs/typeorm'

import { CartModule } from './cart/cart.module'
import { CatalogModule } from './catalog/catalog.module'
import { HealthModule } from './health/health.module'
import { RedisModule } from './redis/redis.module'
import { RepositoriesModule } from './repositories/repositories.module'
import { dataSourceOptions } from './db/data-source-options'

@Module({
  imports: [
    TypeOrmModule.forRoot(dataSourceOptions()),
    RedisModule,
    RepositoriesModule,
    CatalogModule,
    CartModule,
    HealthModule,
  ],
})
export class AppModule {}
