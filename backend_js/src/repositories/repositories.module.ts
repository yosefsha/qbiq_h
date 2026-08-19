/**
 * Where storage implementations are bound to the domain interfaces.
 *
 * One module, and one `PRODUCT_REPOSITORY` binding, deliberately: the
 * catalogue and the Cart must resolve a product id through the *same*
 * repository. When each side owned its own provider in the Python service,
 * they disagreed about what a product id even was — the catalogue served the
 * database primary key (`"8"`) while the Cart resolved a slug of the product
 * name (`"codesight-static-analyzer-team-licence"`), so a `productId` taken
 * straight from a listing 404'd on `POST /api/cart/items`. One binding makes
 * that class of drift impossible rather than merely unlikely.
 *
 * Global, so the catalogue, cart and health modules inject the tokens without
 * each re-importing this module — and so a test can override a single token
 * and have both halves of the API see the replacement.
 */

import { Global, Module } from '@nestjs/common'
import type { Redis } from 'ioredis'
import { DataSource } from 'typeorm'

import { CART_REPOSITORY, PRODUCT_REPOSITORY, ProductRepository } from '../domain/repositories'
import { CachedProductRepository } from './cached-product.repository'
import { RedisCartRepository } from './redis-cart.repository'
import { SqlProductRepository } from './sql-product.repository'
import { REDIS_CLIENT } from '../redis/redis.constants'
import { settings } from '../config/settings'

@Global()
@Module({
  providers: [
    {
      provide: PRODUCT_REPOSITORY,
      inject: [DataSource, REDIS_CLIENT],
      // To remove the cache entirely, return the `SqlProductRepository` alone.
      useFactory: (dataSource: DataSource, redis: Redis): ProductRepository =>
        new CachedProductRepository(
          new SqlProductRepository(dataSource),
          redis,
          settings.cacheTtlSeconds,
        ),
    },
    {
      provide: CART_REPOSITORY,
      inject: [REDIS_CLIENT, PRODUCT_REPOSITORY],
      useFactory: (redis: Redis, products: ProductRepository) =>
        new RedisCartRepository(redis, products, settings.sessionTtlSeconds),
    },
  ],
  exports: [PRODUCT_REPOSITORY, CART_REPOSITORY],
})
export class RepositoriesModule {}
