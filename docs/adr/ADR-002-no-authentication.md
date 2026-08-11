# No authentication; Shoppers stay anonymous

The storefront has no login, registration, or user accounts. The session cookie from [ADR-001](./ADR-001-server-owned-cart.md) identifies an anonymous Shopper for the sole purpose of owning a Cart, and nothing else hangs off it. This is a deliberate omission, not an oversight.

## Why

The assignment scores none of it — there are no accounts, orders, or per-user features anywhere in the requirements — while a credible implementation costs roughly three hours of a six-hour budget: password hashing and user records (~1h), the Vue login and registration views, auth store, route guard and 401 handling (~1–1.5h), and cart-merge-on-login with its tests (~0.5h). Paying that means cutting accessibility work, CI, or test coverage, all of which the brief *does* ask for.

The deciding factor is that omitting it costs nothing architecturally. Because sessions are server-issued and server-stored, adding authentication later is additive — a `userId` field on an existing session record — rather than a redesign. Had the Cart been client-owned in `localStorage`, this decision would have been much harder to reverse.

## Consequences

- Any Shopper who clears cookies, or whose session TTL lapses, silently gets a new empty Cart. Acceptable with nothing of value at stake; unacceptable the moment orders exist.
- Cart endpoints authorise nothing beyond possession of the session cookie. There is no ownership check to write because there is no owner to check against.
- The merge semantics for combining an anonymous Cart with an account Cart at login are **undecided**, not decided-and-implemented. Whoever adds auth must settle them: summing quantities and clamping to stock is the conventional answer, but it is a domain choice, not plumbing.
- No password storage means no credential-handling surface to secure, review, or get wrong.
