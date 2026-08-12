/**
 * The single place a Product's price is turned into a display string.
 *
 * Prices come off the wire as integer minor units (e.g. cents) plus an ISO
 * 4217 currency code (see `types.ts`) and must stay that way everywhere
 * except right here: dividing by 100 earlier and passing a float around
 * would let rounding drift back into a value that's supposed to be exact
 * integer arithmetic. FE-03 and FE-04 both render a price, so this helper
 * is shared rather than reimplemented per component.
 */
import type { CurrencyCode } from './types'

/**
 * `en-US` rather than the browser's locale: price formatting must be
 * deterministic (same output in every browser, every CI run, every test)
 * rather than vary with wherever the app happens to be running.
 */
const LOCALE = 'en-US'

/** Formats integer minor units and a currency code as a localized price, e.g. `14900, "USD"` -> `"$149.00"`. */
export function formatMoney(minorUnits: number, currency: CurrencyCode): string {
  return new Intl.NumberFormat(LOCALE, { style: 'currency', currency }).format(minorUnits / 100)
}
