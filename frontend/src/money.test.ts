import { describe, expect, it } from 'vitest'

import { formatMoney } from './money'

describe('formatMoney', () => {
  it('formats integer minor units as a currency string', () => {
    expect(formatMoney(14900, 'USD')).toBe('$149.00')
  })

  it('pads a whole number of minor units to two decimal places', () => {
    expect(formatMoney(999, 'USD')).toBe('$9.99')
  })

  it('formats zero', () => {
    expect(formatMoney(0, 'USD')).toBe('$0.00')
  })

  it('formats a different currency with its own symbol', () => {
    expect(formatMoney(14900, 'EUR')).toBe('€149.00')
  })
})
