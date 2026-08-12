import { describe, expect, it } from 'vitest'

import { formatMoney } from './money'

/**
 * One shared suite. FE-02, FE-03 and FE-04 each wrote their own version of
 * these tests against their own copy of `money.ts`; this is the union of the
 * distinct cases the three covered, so no assertion was lost when the three
 * copies were converged into one.
 */
describe('formatMoney', () => {
  it('formats integer minor units as a currency string', () => {
    expect(formatMoney(14900, 'USD')).toBe('$149.00')
  })

  it('divides by 100 only at the formatting boundary, so odd cents round-trip exactly', () => {
    expect(formatMoney(1999, 'USD')).toBe('$19.99')
  })

  it('pads a whole number of minor units to two decimal places', () => {
    expect(formatMoney(1500, 'USD')).toBe('$15.00')
  })

  it('formats the smallest representable amount', () => {
    expect(formatMoney(1, 'USD')).toBe('$0.01')
  })

  it('formats zero', () => {
    expect(formatMoney(0, 'USD')).toBe('$0.00')
  })

  it('respects the currency code rather than hardcoding USD', () => {
    expect(formatMoney(14900, 'EUR')).toBe('€149.00')
  })

  it('pins the locale, so output does not vary with the machine running the test', () => {
    // The guard on the reason `money.ts` hardcodes `en-US`: with the browser
    // default locale, this same call renders "149,00 €" on a de-DE machine and
    // the assertion above would pass or fail depending on where it ran.
    expect(formatMoney(14900, 'EUR')).toBe('€149.00')
    expect(formatMoney(14900, 'USD')).toBe('$149.00')
  })
})
