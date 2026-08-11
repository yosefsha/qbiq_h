# Server-owned Cart, keyed by an anonymous session cookie

The brief asks for both Pinia cart state and cart API endpoints, which leaves the Cart with two possible homes. We made the server authoritative: a Cart lives in Redis under `cart:{sessionId}` with a sliding TTL, prices and totals are computed server-side, and the Pinia store mirrors the server's response rather than owning the Cart itself. Shoppers are anonymous — the API mints an opaque `secrets.token_urlsafe(32)` token on the first Cart request and returns it as an `HttpOnly; Secure; SameSite=Lax` cookie.

## Considered Options

- **Pinia as sole source of truth, persisted to `localStorage`.** Rejected: it reduces the required "shopping cart operations" endpoints to a stub, and a total computed in the browser is a total the browser can edit.
- **A signed stateless token (JWT) instead of an opaque session id.** Rejected: it buys nothing here, because a shared session store already exists in Redis, and it inherits a revocation problem — a stolen token stays valid until expiry, and "log out everywhere" needs a denylist that reinvents the session table. Stateless tokens earn their keep when you are trying to avoid a session store, not when you already run one.
- **Client-generated session id sent as an `X-Session-Id` header.** Cheaper to build — no CORS credential handling, testable with a bare `curl` — but rejected on ownership grounds. The id is an unauthenticated claim over an enumerable namespace, so any client can read or mutate another's Cart, and `localStorage` hands the id to any script on the page. Harmless while a Cart holds nothing of value; a straight IDOR the moment an address or an order does.

## Consequences

- `allow_credentials=True` forbids a wildcard CORS origin, so allowed origins become explicit configuration.
- The `Secure` flag must be config-driven, or the cookie is silently dropped over plain HTTP in a local Compose run.
- Serving the API path-routed under the SPA's own domain in production keeps the cookie same-site, avoiding a weakening to `SameSite=None`.
- Every Cart mutation is a network round trip; the Pinia store carries loading and error state for each, which the brief's loading-state requirement wants anyway.
- If authentication is ever added, a session Cart must be merged into the authenticated Shopper's Cart at login. Out of scope here, deliberately.
