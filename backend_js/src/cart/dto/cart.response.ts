/**
 * The rendered Cart, and the projection that builds it.
 *
 * Every price here comes from the `Product` the repository re-resolved against
 * the catalogue for this call — never a value read back from Redis — so a
 * catalogue price change is reflected on the very next response for an
 * existing Cart, and `totalMinor` is exact integer addition with no floats or
 * rounding anywhere in the chain.
 */

import { Cart, cartSubtotalMinor, lineItemSubtotalMinor } from '../../domain/cart'
import { pyRepr } from '../../common/py-repr'

/**
 * Reported on an empty Cart. A Cart carries no currency of its own — every
 * `Product` does — so an empty Cart has no line to read one from. Every row
 * the seeder inserts is USD, and nothing in the domain lets a Shopper choose a
 * different one, so this is the storefront's one real currency today rather
 * than an arbitrary placeholder. If the catalogue ever goes multi-currency,
 * this needs to become real per-Shopper or per-locale configuration.
 */
export const DEFAULT_CART_CURRENCY = 'USD'

export interface CartLineItemView {
  productId: string
  name: string
  unitPriceMinor: number
  quantity: number
  subtotalMinor: number
}

export interface CartView {
  items: CartLineItemView[]
  totalMinor: number
  currency: string
}

export function toCartView(cart: Cart): CartView {
  const items = cart.items.map((item) => ({
    productId: item.product.id,
    name: item.product.name,
    unitPriceMinor: item.product.priceMinor,
    quantity: item.quantity,
    subtotalMinor: lineItemSubtotalMinor(item),
  }))

  const currencies = new Set(cart.items.map((item) => item.product.currency))
  if (currencies.size > 1) {
    // Every line is priced by the same catalogue, so a Cart is not supposed to
    // be able to reach this state. Treated as a data-integrity bug rather than
    // a client error: it is left to throw (surfacing as a 500) rather than
    // silently summed as though the currencies were the same unit.
    const listed = [...currencies].sort().map(pyRepr).join(', ')
    throw new Error(`Cart ${pyRepr(cart.sessionId)} mixes currencies: [${listed}]`)
  }
  const currency = currencies.size === 1 ? [...currencies][0] : DEFAULT_CART_CURRENCY

  return { items, totalMinor: cartSubtotalMinor(cart), currency }
}
