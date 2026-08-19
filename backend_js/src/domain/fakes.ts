/**
 * In-memory fake satisfying both `ProductRepository` and `CartRepository`.
 *
 * This is a deliverable, not a private test helper: the controller tests
 * construct it inline to exercise business logic without a real Postgres or
 * Redis instance, exactly as `backend/app/domain/fakes.py` does on the Python
 * side.
 */

import { Cart, LineItem, makeLineItem } from './cart'
import {
  Category,
  Product,
  ProductDetail,
  ProductPage,
  ProductQuery,
  SortDirection,
  SortKey,
  isProductDetail,
} from './catalog'
import { UnknownProductError, UnknownSortKeyError } from './errors'
import { CartRepository, ProductRepository } from './repositories'

type SortValue = string | number
type SortFunc = (product: Product) => SortValue

const SORT_FUNCS: Readonly<Record<SortKey, SortFunc>> = {
  [SortKey.NAME]: (product) => product.name.toLowerCase(),
  [SortKey.PRICE]: (product) => product.priceMinor,
}

function compare(left: SortValue, right: SortValue): number {
  if (left < right) {
    return -1
  }
  return left > right ? 1 : 0
}

/**
 * A storage-free stand-in for `ProductRepository` and `CartRepository`.
 *
 * Holds a fixed product catalogue, seeded at construction, and a mutable,
 * in-process map of session id -> Cart.
 */
export class InMemoryRepository implements ProductRepository, CartRepository {
  private readonly products = new Map<string, Product>()
  private readonly carts = new Map<string, Cart>()

  constructor(products: Iterable<Product> = []) {
    for (const product of products) {
      this.products.set(product.id, product)
    }
  }

  // -- ProductRepository ---------------------------------------------

  async listProducts(query: ProductQuery): Promise<ProductPage> {
    let items = [...this.products.values()]

    if (query.nameContains) {
      const needle = query.nameContains.toLowerCase()
      items = items.filter((product) => product.name.toLowerCase().includes(needle))
    }

    if (query.categorySlug !== null) {
      items = items.filter((product) => product.category.slug === query.categorySlug)
    }

    const sortFunc = SORT_FUNCS[query.sort]
    if (sortFunc === undefined) {
      throw new UnknownSortKeyError(query.sort)
    }

    const descending = query.direction === SortDirection.DESC
    items.sort((left, right) => {
      const ordering = compare(sortFunc(left), sortFunc(right))
      return descending ? -ordering : ordering
    })

    const total = items.length
    return { items: items.slice(query.offset, query.offset + query.limit), total }
  }

  async getProduct(productId: string): Promise<Product | null> {
    return this.products.get(productId) ?? null
  }

  /**
   * Returns the seeded `ProductDetail` for `productId`, if any.
   *
   * Returns `null` for a product seeded only as a summary `Product`, matching
   * a storage-backed implementation that finds the row but has no detail
   * content for it.
   */
  async getProductDetail(productId: string): Promise<ProductDetail | null> {
    const product = this.products.get(productId)
    if (product === undefined || !isProductDetail(product)) {
      return null
    }
    return product
  }

  /**
   * Derives the category list from the seeded products.
   *
   * Deduplicated by slug and sorted by slug, matching the deterministic
   * ordering `SqlProductRepository.listCategories` gets from `ORDER BY slug`,
   * so tests written against the fake see the same ordering a real
   * Postgres-backed repository would produce.
   */
  async listCategories(): Promise<readonly Category[]> {
    const bySlug = new Map<string, Category>()
    for (const product of this.products.values()) {
      bySlug.set(product.category.slug, product.category)
    }
    return [...bySlug.keys()].sort().map((slug) => bySlug.get(slug) as Category)
  }

  // -- CartRepository ---------------------------------------------------

  async getCart(sessionId: string): Promise<Cart> {
    return this.carts.get(sessionId) ?? { sessionId, items: [] }
  }

  async addItem(sessionId: string, productId: string, quantity: number): Promise<Cart> {
    if (quantity <= 0) {
      throw new RangeError('quantity must be > 0')
    }

    const product = this.requireProduct(productId)
    const itemsByProduct = await this.itemsByProduct(sessionId)
    const existing = itemsByProduct.get(productId)
    const newQuantity = quantity + (existing ? existing.quantity : 0)
    itemsByProduct.set(productId, makeLineItem(product, newQuantity))
    return this.saveCart(sessionId, itemsByProduct)
  }

  async setQuantity(
    sessionId: string,
    productId: string,
    quantity: number,
  ): Promise<Cart> {
    if (quantity < 0) {
      throw new RangeError('quantity must be >= 0')
    }

    const itemsByProduct = await this.itemsByProduct(sessionId)
    if (quantity === 0) {
      itemsByProduct.delete(productId)
    } else {
      itemsByProduct.set(productId, makeLineItem(this.requireProduct(productId), quantity))
    }
    return this.saveCart(sessionId, itemsByProduct)
  }

  async removeItem(sessionId: string, productId: string): Promise<Cart> {
    const itemsByProduct = await this.itemsByProduct(sessionId)
    itemsByProduct.delete(productId)
    return this.saveCart(sessionId, itemsByProduct)
  }

  private async itemsByProduct(sessionId: string): Promise<Map<string, LineItem>> {
    const cart = await this.getCart(sessionId)
    return new Map(cart.items.map((item) => [item.product.id, item]))
  }

  private saveCart(sessionId: string, itemsByProduct: Map<string, LineItem>): Cart {
    const cart: Cart = { sessionId, items: [...itemsByProduct.values()] }
    this.carts.set(sessionId, cart)
    return cart
  }

  private requireProduct(productId: string): Product {
    const product = this.products.get(productId)
    if (product === undefined) {
      throw new UnknownProductError(productId)
    }
    return product
  }
}
