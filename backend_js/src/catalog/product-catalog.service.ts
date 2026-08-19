/**
 * Business logic behind the product catalogue HTTP surface.
 *
 * Kept separate from the controller so the route handlers stay thin: this
 * builds the domain `ProductQuery`, validates an inbound `category` filter,
 * and converts domain objects into the wire shapes. It depends only on the
 * `ProductRepository` interface, never on a concrete storage implementation,
 * so it works unchanged against `SqlProductRepository` in production and
 * `InMemoryRepository` in tests.
 */

import { Inject, Injectable } from '@nestjs/common'

import {
  SortDirection,
  SortKey,
  makeProductQuery,
} from '../domain/catalog'
import { UnknownCategoryError } from '../domain/errors'
import { PRODUCT_REPOSITORY, ProductRepository } from '../domain/repositories'
import {
  CategoryResponse,
  ProductDetailResponse,
  ProductListResponse,
  toCategoryResponse,
  toProductDetailResponse,
  toProductListResponse,
} from './dto/product.response'

export interface ListProductsArgs {
  name: string | null
  category: string | null
  sort: SortKey
  direction: SortDirection
  limit: number
  offset: number
}

@Injectable()
export class ProductCatalogService {
  constructor(
    @Inject(PRODUCT_REPOSITORY) private readonly repository: ProductRepository,
  ) {}

  /**
   * Returns a page of the catalogue matching the given filters.
   *
   * @throws UnknownCategoryError if `category` names no known `Category` slug.
   * @throws UnknownSortKeyError never, in practice — `sort` is an enum at the
   *   HTTP boundary — but the controller still maps it to 422 as a backstop.
   */
  async listProducts(args: ListProductsArgs): Promise<ProductListResponse> {
    if (args.category !== null) {
      await this.requireKnownCategory(args.category)
    }

    const query = makeProductQuery({
      nameContains: args.name,
      categorySlug: args.category,
      sort: args.sort,
      direction: args.direction,
      limit: args.limit,
      offset: args.offset,
    })
    const page = await this.repository.listProducts(query)
    return toProductListResponse(page, args.limit, args.offset)
  }

  /** Returns the detail page for `productId`, or `null` if absent. */
  async getProductDetail(productId: string): Promise<ProductDetailResponse | null> {
    const detail = await this.repository.getProductDetail(productId)
    return detail === null ? null : toProductDetailResponse(detail)
  }

  /** Returns every known `Category`. */
  async listCategories(): Promise<CategoryResponse[]> {
    const categories = await this.repository.listCategories()
    return categories.map(toCategoryResponse)
  }

  private async requireKnownCategory(slug: string): Promise<void> {
    const known = await this.repository.listCategories()
    if (!known.some((category) => category.slug === slug)) {
      throw new UnknownCategoryError(slug)
    }
  }
}
