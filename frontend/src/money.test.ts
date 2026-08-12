import { describe, expect, it } from 'vitest'

import { formatMoney } from './money'

describe('formatMoney', () => {
  it('formats integer minor units as a localized price', () => {
    expect(formatMoney(14900, 'USD')).toBe('$149.00')
  })

  it('divides by 100 only at the formatting boundary, so odd cents round-trip exactly', () => {
    expect(formatMoney(999, 'USD')).toBe('$9.99')
    expect(formatMoney(1, 'USD')).toBe('$0.01')
  })

  it('formats zero', () => {
    expect(formatMoney(0, 'USD')).toBe('$0.00')
  })

  it('respects the currency code rather than always rendering USD', () => {
    expect(formatMoney(14900, 'EUR')).toBe('€149.00')
  })
})
