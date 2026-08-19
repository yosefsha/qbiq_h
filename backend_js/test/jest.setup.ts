/**
 * Keeps the suite's output readable.
 *
 * The service logs a JSON line per request by design, which would bury the
 * test report under thousands of them. `logging.spec.ts` constructs its own
 * logger with an explicit threshold, so it is unaffected by this.
 */
process.env.LOG_LEVEL = process.env.LOG_LEVEL ?? 'CRITICAL'
