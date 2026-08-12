/**
 * The single place a Product's price is turned into a display string.
 *
 * Prices come off the wire as integer minor units (e.g. cents) plus an ISO
 * 4217 currency code (see `types.ts`) and must stay that way everywhere
 * except right here: dividing by 100 earlier and passing a float around
 * would let rounding drift back into a value that's supposed to be exact
 * integer arithmetic. The catalogue, the product detail page, and the cart
 * all render prices, so this helper is shared rather than reimplemented
 * per component.
 */
import type { CurrencyCode } from './types'

/**
 * `en-US` rather than the browser's locale: price formatting must be
 * deterministic (same output in every browser, every CI run, every test)
 * rather than vary with wherever the app happens to be running. A
 * locale-dependent formatter makes any assertion on a formatted string
 * quietly machine-specific.
 */
const LOCALE = 'en-US'

/**
 * `Intl.NumberFormat` is expensive to construct and safe to reuse, and a
 * catalogue page formats one price per row — so one formatter is cached per
 * currency rather than rebuilt on every call.
 */
const formattersByCurrency = new Map<CurrencyCode, Intl.NumberFormat>()

function formatterFor(currency: CurrencyCode): Intl.NumberFormat {
  const cached = formattersByCurrency.get(currency)
  if (cached) {
    return cached
  }
  const formatter = new Intl.NumberFormat(LOCALE, { style: 'currency', currency })
  formattersByCurrency.set(currency, formatter)
  return formatter
}

/** Formats integer minor units and a currency code as a price, e.g. `14900, "USD"` -> `"$149.00"`. */
export function formatMoney(minorUnits: number, currency: CurrencyCode): string {
  return formatterFor(currency).format(minorUnits / 100)
}
