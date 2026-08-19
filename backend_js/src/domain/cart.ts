/**
 * Cart domain types: line items and the Cart itself.
 *
 * A Cart is server-owned and keyed by an anonymous Shopper's opaque session
 * id (see `docs/adr/ADR-001-server-owned-cart.md`). A `LineItem` embeds the
 * full `Product` it refers to, rather than duplicating its
 * name/price/currency, so a rendered Cart never needs a second lookup against
 * `ProductRepository` and its subtotal is always integer minor-unit
 * arithmetic.
 */

import { Product } from './catalog'

/** One Product within a Cart, together with the quantity wanted of it. */
export interface LineItem {
  readonly product: Product
  readonly quantity: number
}

/** Builds a `LineItem`, enforcing a positive quantity. */
export function makeLineItem(product: Product, quantity: number): LineItem {
  if (quantity <= 0) {
    throw new RangeError('quantity must be > 0')
  }
  return { product, quantity }
}

/** This line's price, quantity included, in integer minor units. */
export function lineItemSubtotalMinor(item: LineItem): number {
  return item.product.priceMinor * item.quantity
}

/** The set of Products a Shopper intends to buy. */
export interface Cart {
  readonly sessionId: string
  readonly items: readonly LineItem[]
}

/** Sum of every line item's subtotal, in integer minor units. */
export function cartSubtotalMinor(cart: Cart): number {
  return cart.items.reduce((total, item) => total + lineItemSubtotalMinor(item), 0)
}
