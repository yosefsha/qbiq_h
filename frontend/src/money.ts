/**
 * The single place that turns an integer minor-unit price into a display
 * string. Every price on the wire is `{ minorUnits, currency }` (see
 * `types.ts`) precisely so formatting only ever happens here, once, via
 * `Intl.NumberFormat` — dividing by 100 is a formatting-boundary concern,
 * never a step in cart or total arithmetic.
 */
import type { CurrencyCode } from './types'

/**
 * `Intl.NumberFormat` instances are expensive to construct and safe to
 * reuse, so one is cached per currency rather than built on every call.
 */
const formattersByCurrency = new Map<CurrencyCode, Intl.NumberFormat>()

function formatterFor(currency: CurrencyCode): Intl.NumberFormat {
  const cached = formattersByCurrency.get(currency)
  if (cached) {
    return cached
  }
  const formatter = new Intl.NumberFormat(undefined, { style: 'currency', currency })
  formattersByCurrency.set(currency, formatter)
  return formatter
}

/**
 * Formats an integer minor-unit amount (e.g. `14900` cents) plus an ISO 4217
 * currency code into a localised display string (e.g. `"$149.00"`).
 */
export function formatMoney(minorUnits: number, currency: CurrencyCode): string {
  return formatterFor(currency).format(minorUnits / 100)
}
