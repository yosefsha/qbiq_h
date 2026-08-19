/**
 * Product catalogue routes.
 *
 * Thin wiring only: `ListProductsQuery` enforces paging bounds and valid
 * sort/direction values before a handler runs, so those surface as 422 with no
 * business logic involved. Everything else is delegated to
 * `ProductCatalogService`.
 *
 * No TypeORM import may appear in this module: every handler goes through the
 * `PRODUCT_REPOSITORY` token, which production binds to a cached
 * Postgres-backed repository and tests bind to `InMemoryRepository` — either
 * way, this module never knows which one it got.
 */

import {
  Controller,
  Get,
  HttpException,
  HttpStatus,
  NotFoundException,
  Param,
  Query,
  UnprocessableEntityException,
} from '@nestjs/common'

import { pyRepr } from '../common/py-repr'
import { SortDirection, SortKey } from '../domain/catalog'
import { UnknownCategoryError, UnknownSortKeyError } from '../domain/errors'
import { ListProductsQuery } from './dto/list-products.query'
import {
  CategoryResponse,
  ProductDetailResponse,
  ProductListResponse,
} from './dto/product.response'
import { ProductCatalogService } from './product-catalog.service'

@Controller('api')
export class ProductsController {
  constructor(private readonly catalog: ProductCatalogService) {}

  /** Lists the catalogue, filtered, sorted, and paged. */
  @Get('products')
  async listProducts(@Query() query: ListProductsQuery): Promise<ProductListResponse> {
    try {
      return await this.catalog.listProducts({
        name: query.name ?? null,
        category: query.category ?? null,
        sort: query.sort ?? SortKey.NAME,
        direction: query.direction ?? SortDirection.ASC,
        limit: query.limit ?? 20,
        offset: query.offset ?? 0,
      })
    } catch (cause) {
      throw toHttpError(cause)
    }
  }

  /**
   * Returns the detail page for `productId`.
   *
   * `productId` is a plain string rather than a parsed integer: a non-numeric
   * id such as `/api/products/abc` must 404, matching the repository's own
   * contract of returning `null` for it, rather than being rejected as a 422
   * path-parameter type error before the repository is even asked.
   */
  @Get('products/:productId')
  async getProduct(@Param('productId') productId: string): Promise<ProductDetailResponse> {
    const detail = await this.catalog.getProductDetail(productId)
    if (detail === null) {
      throw new NotFoundException(`Product ${pyRepr(productId)} not found`)
    }
    return detail
  }

  /** Lists every category, for the catalogue's filter UI. */
  @Get('categories')
  async listCategories(): Promise<CategoryResponse[]> {
    return this.catalog.listCategories()
  }
}

/**
 * Maps a domain error onto its HTTP status.
 *
 * An unknown category slug and an unknown sort key are both 422 — an empty
 * result set and an invalid filter are different outcomes and must not look
 * identical to the client. A `RangeError` is the paging invariants' own
 * backstop; the query bounds already enforce them, so it should be
 * unreachable.
 */
function toHttpError(cause: unknown): unknown {
  if (cause instanceof UnknownCategoryError) {
    return new UnprocessableEntityException(`Unknown category: ${pyRepr(cause.slug)}`)
  }
  if (cause instanceof UnknownSortKeyError) {
    return new UnprocessableEntityException(
      `Unknown sort key: ${pyRepr(String(cause.sortKey))}`,
    )
  }
  if (cause instanceof RangeError) {
    return new HttpException(cause.message, HttpStatus.UNPROCESSABLE_ENTITY)
  }
  return cause
}
