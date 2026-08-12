/**
 * Formats a price from the API's wire format — integer minor units
 * (e.g. cents) plus an ISO 4217 currency code — into a display string, via
 * `Intl.NumberFormat`. This is the one place a price is divided by 100:
 * every other module works with the raw integer (see `types.ts`'s note on
 * why prices are never floats) and only converts here, at the formatting
 * boundary.
 */

/**
 * Fixed rather than derived from the browser: the SPA has no i18n story yet,
 * and letting the display locale drift with the visitor's browser would make
 * this function's output non-deterministic for the same input.
 */
const DISPLAY_LOCALE = 'en-US'

export function formatPriceMinor(minor: number, currency: string): string {
  return new Intl.NumberFormat(DISPLAY_LOCALE, { style: 'currency', currency }).format(minor / 100)
}
