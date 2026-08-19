/**
 * Boots the real HTTP stack over fake storage.
 *
 * Every global the application installs in `main.ts` — CORS, the session
 * cookie middleware, the request-id middleware, the 422 validation pipe and
 * the exception filter — is installed here too, in the same order. That is the
 * point: a test that asserts a cookie survives a 422, or that a 500 keeps its
 * CORS headers, is worthless against a stripped-down app that never had the
 * layers under test.
 *
 * Only the storage is swapped: `InMemoryRepository` satisfies both repository
 * interfaces, and `FakeRedis` stands in for the session store's client.
 */

import { HttpStatus, INestApplication, ValidationPipe } from '@nestjs/common'
import { Test } from '@nestjs/testing'

import { AllExceptionsFilter } from '../src/common/all-exceptions.filter'
import { CartController } from '../src/cart/cart.controller'
import { InMemoryRepository } from '../src/domain/fakes'
import { ProductCatalogService } from '../src/catalog/product-catalog.service'
import { ProductsController } from '../src/catalog/products.controller'
import { REDIS_CLIENT } from '../src/redis/redis.constants'
import { REQUEST_ID_HEADER, requestIdMiddleware } from '../src/common/request-id.middleware'
import { SessionStore } from '../src/common/session/session.store'
import { sessionCookieMiddleware } from '../src/common/session/session.middleware'
import {
  CART_REPOSITORY,
  CartRepository,
  PRODUCT_REPOSITORY,
  ProductRepository,
} from '../src/domain/repositories'
import { Product } from '../src/domain/catalog'
import { settings } from '../src/config/settings'
import { FakeRedis } from './fake-redis'

export interface TestApp {
  app: INestApplication
  repository: InMemoryRepository
  redis: FakeRedis
  close: () => Promise<void>
}

export interface TestAppOptions {
  products?: Product[]
  /** Swap either repository, e.g. for one that throws. */
  productRepository?: ProductRepository
  cartRepository?: CartRepository
  redis?: FakeRedis
  /** Extra controllers, for the middleware tests' throwaway routes. */
  controllers?: NonNullable<Parameters<typeof Test.createTestingModule>[0]['controllers']>
}

export async function createTestApp(options: TestAppOptions = {}): Promise<TestApp> {
  const repository = new InMemoryRepository(options.products ?? [])
  const redis = options.redis ?? new FakeRedis()

  const moduleRef = await Test.createTestingModule({
    controllers: [
      ProductsController,
      CartController,
      ...(options.controllers ?? []),
    ],
    providers: [
      ProductCatalogService,
      SessionStore,
      { provide: PRODUCT_REPOSITORY, useValue: options.productRepository ?? repository },
      { provide: CART_REPOSITORY, useValue: options.cartRepository ?? repository },
      { provide: REDIS_CLIENT, useValue: redis.asRedis() },
    ],
  }).compile()

  const app = moduleRef.createNestApplication()

  app.enableCors({
    origin: [...settings.allowedOrigins],
    credentials: true,
    methods: ['GET', 'POST', 'PATCH', 'PUT', 'DELETE', 'OPTIONS', 'HEAD'],
    allowedHeaders: ['*'],
    exposedHeaders: [REQUEST_ID_HEADER],
  })
  app.use(sessionCookieMiddleware)
  app.use(requestIdMiddleware)
  app.useGlobalPipes(
    new ValidationPipe({
      transform: true,
      errorHttpStatusCode: HttpStatus.UNPROCESSABLE_ENTITY,
    }),
  )
  app.useGlobalFilters(new AllExceptionsFilter())

  await app.init()

  return { app, repository, redis, close: () => app.close() }
}

/**
 * Normalises a `Set-Cookie` header, which an HTTP client may hand back as a
 * single string or as a list depending on how many cookies were set.
 */
function setCookies(header: unknown): string[] {
  if (Array.isArray(header)) {
    return header as string[]
  }
  return typeof header === 'string' ? [header] : []
}

/** Returns the `session_id` cookie's full attribute string, if present. */
export function sessionCookieHeader(header: unknown): string | null {
  return setCookies(header).find((value) => value.startsWith('session_id=')) ?? null
}

/** Reads the `session_id` cookie's value out of a `Set-Cookie` header. */
export function sessionCookieValue(header: unknown): string | null {
  const cookie = sessionCookieHeader(header)
  return cookie === null ? null : cookie.split(';')[0].slice('session_id='.length)
}
