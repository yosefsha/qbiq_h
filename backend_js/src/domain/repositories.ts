/**
 * Repository interfaces every storage-backed implementation codes against.
 *
 * No TypeORM entity, query builder, or ioredis type may appear in any
 * signature here — that constraint is the entire point of the abstraction
 * (see `docs/adr/ADR-003-managed-aws-data-tier.md`). Both interfaces are also
 * satisfied by `InMemoryRepository`, so tests never need a real database.
 *
 * The methods return promises where the Python originals are synchronous:
 * every Node driver worth using is async, and there is no equivalent of
 * FastAPI's threadpool escape hatch. Nothing else about the contract changes.
 */

import { Cart } from './cart'
import { Category, Product, ProductDetail, ProductPage, ProductQuery } from './catalog'

/**
 * DI token for the single, shared `ProductRepository`.
 *
 * One token, injected by both the catalogue and the cart, deliberately: while
 * each side owned its own provider in the Python service, the catalogue served
 * database primary keys while the Cart resolved a slug of the product name, so
 * a `productId` copied from a listing 404'd on `POST /api/cart/items`. One
 * token makes that class of drift impossible rather than merely unlikely.
 */
export const PRODUCT_REPOSITORY = Symbol('ProductRepository')

/** DI token for the `CartRepository`. */
export const CART_REPOSITORY = Symbol('CartRepository')

/** Read access to the product catalogue. */
export interface ProductRepository {
  /**
   * Returns a page of products matching `query`.
   *
   * @throws UnknownSortKeyError if `query.sort` names no known ordering.
   */
  listProducts(query: ProductQuery): Promise<ProductPage>

  /**
   * Returns every `Category`, deduplicated, ordered by `slug`.
   *
   * Used by `GET /api/categories` and to validate an inbound `category`
   * filter — an unknown slug must 422 rather than silently returning an
   * empty page.
   */
  listCategories(): Promise<readonly Category[]>

  /**
   * Returns the product with `productId`, or `null` if it does not exist.
   *
   * Returns the summary shape used by list views. For the detail page, which
   * additionally needs the long description and reviews, use
   * `getProductDetail` rather than downcasting this result.
   */
  getProduct(productId: string): Promise<Product | null>

  /**
   * Returns the full detail for `productId`, or `null` if absent.
   *
   * Implementations load reviews here and NOT in `listProducts`, which would
   * otherwise issue a query per row.
   */
  getProductDetail(productId: string): Promise<ProductDetail | null>
}

/** Read/write access to a Shopper's Cart, keyed by session id. */
export interface CartRepository {
  /** Returns the Cart for `sessionId`, creating an empty one if needed. */
  getCart(sessionId: string): Promise<Cart>

  /**
   * Adds `quantity` of `productId` to the Cart, returning the updated Cart.
   *
   * @throws UnknownProductError if `productId` does not exist.
   */
  addItem(sessionId: string, productId: string, quantity: number): Promise<Cart>

  /**
   * Sets the quantity of `productId` in the Cart to exactly `quantity`.
   *
   * A quantity of `0` removes the line item.
   *
   * @throws UnknownProductError if `productId` does not exist and quantity > 0.
   */
  setQuantity(sessionId: string, productId: string, quantity: number): Promise<Cart>

  /**
   * Removes `productId` from the Cart, returning the updated Cart.
   *
   * A no-op, not an error, if the product was not in the Cart.
   */
  removeItem(sessionId: string, productId: string): Promise<Cart>
}
