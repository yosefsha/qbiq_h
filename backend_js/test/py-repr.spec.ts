/**
 * The quoting rule that keeps error bodies identical across the two backends.
 *
 * The expected values below are what `repr()` returns in Python; if this ever
 * disagrees, a response-parity diff between the services flags every 404.
 */

import { pyRepr } from '../src/common/py-repr'

describe('pyRepr', () => {
  it.each([
    ['abc', "'abc'"],
    ['', "''"],
    ['42', "'42'"],
    ['it-is', "'it-is'"],
  ])('renders %p as %p', (value, expected) => {
    expect(pyRepr(value)).toBe(expected)
  })

  it("switches to double quotes when the value contains a single quote", () => {
    expect(pyRepr("it's")).toBe('"it\'s"')
  })

  it('escapes a single quote when double quotes are also present', () => {
    expect(pyRepr(`he said "it's"`)).toBe(`'he said "it\\'s"'`)
  })

  it('escapes backslashes', () => {
    expect(pyRepr('a\\b')).toBe("'a\\\\b'")
  })
})
