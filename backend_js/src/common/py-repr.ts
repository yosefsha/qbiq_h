/**
 * Formats a string the way Python's `repr` does.
 *
 * The two backends serve the same error bodies, and the Python service builds
 * its messages with `!r` — `Product '42' not found`, single quotes and all.
 * `JSON.stringify` would render the same message with double quotes, which is
 * a difference a response-parity diff would flag on every 404. So the quoting
 * rule is reproduced here rather than left to drift.
 *
 * Python prefers single quotes, switching to double only when the value
 * contains a single quote and no double quote.
 */
export function pyRepr(value: string): string {
  const escaped = value.replace(/\\/g, '\\\\')
  if (escaped.includes("'") && !escaped.includes('"')) {
    return `"${escaped}"`
  }
  return `'${escaped.replace(/'/g, "\\'")}'`
}
