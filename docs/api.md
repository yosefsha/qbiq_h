# API reference

Every shape below was read out of the code and then verified against a running stack
with `curl`. The live schema is served at `/openapi.json`, with Swagger UI at `/docs`.

Examples use `http://localhost:8000`; substitute your `API_PORT`, or drop the port and
go through nginx (`http://localhost:${WEB_PORT}/api/...`), which reaches the same
handlers.

For what a Product, Category, Review, Cart or Line Item *is*, see
[`CONTEXT.md`](../CONTEXT.md).

---

## Conventions

**Money.** Prices are **integer minor units** plus an ISO 4217 currency code:
`{"priceMinor": 1499, "currency": "USD"}` is $14.99. There is no float anywhere in the
chain — not in Postgres, not in Redis, not on the wire. A Cart total is therefore plain
integer addition with nothing to round and no accumulated error
([ADR-003](adr/ADR-003-managed-aws-data-tier.md)). Formatting for display is the SPA's
job (`frontend/src/money.ts`).

**Casing.** camelCase on the wire, snake_case in Python: `priceMinor`,
`shortDescription`, `thumbnailUrl`, `productId`, `totalMinor`, `unitPriceMinor`,
`subtotalMinor`.

**Errors.** Two shapes, both under `detail`:

```jsonc
// Raised by the application (404, and the domain-level 422s)
{"detail": "Unknown category: 'nope'"}

// Raised by FastAPI/Pydantic request validation (422)
{"detail": [{"type": "greater_than_equal", "loc": ["body", "quantity"],
             "msg": "Input should be greater than or equal to 1",
             "input": 0, "ctx": {"ge": 1}}]}
```

A client that wants to display a message should handle both — the SPA's `apiClient`
only reads `detail` when it is a string and falls back to the status text otherwise.

**`X-Request-Id`.** Every response carries one. A well-formed inbound `X-Request-Id`
(`[A-Za-z0-9._~-]{1,128}`) is reused; anything else is replaced with a generated id. It
is in the CORS `expose_headers` list, so browser JavaScript can read it and quote it
against the server logs.

**Session cookie.** Cart routes depend on an anonymous session. The first Cart request
mints one and the response carries:

```
set-cookie: session_id=<43 base64url chars>; HttpOnly; Max-Age=1800; Path=/; SameSite=lax
```

`Secure` is added when `COOKIE_SECURE` is truthy — off locally, because a `Secure`
cookie is dropped silently over plain HTTP. `Max-Age` is `SESSION_TTL_SECONDS`, and the
cookie is rewritten on every request that used a session, so the TTL genuinely slides. A
cookie value that is not exactly 43 characters of the base64url alphabet is treated as
absent and a fresh session is minted. Callers must send cookies (`credentials:
'include'` in `fetch`, `-b/-c` in curl); there is no header or query-parameter form of
the session id, deliberately ([ADR-001](adr/ADR-001-server-owned-cart.md)).

Catalogue routes (`/api/products`, `/api/categories`) and `/health` do not touch the
session and do not set a cookie.

---

## `GET /health`

Liveness probe. Targeted by the ALB target group and by the Compose health check, which
is why it sits outside `/api`. Touches neither Postgres nor Redis — it reports that the
process is up, nothing more.

```bash
curl http://localhost:8000/health
```

```json
{"status": "ok"}
```

| Status | When |
|---|---|
| `200` | Always, if the process is running |

---

## `GET /api/products`

Lists the catalogue, filtered, sorted and paged.

| Parameter | Type | Default | Notes |
|---|---|---|---|
| `name` | string | — | Case-insensitive **substring** match on product name (SQL `ILIKE`) |
| `category` | string | — | Category **slug**, not label. An unknown slug is a `422`, not an empty page |
| `sort` | `name` \| `price` | `name` | Any other value is a `422` |
| `direction` | `asc` \| `desc` | `asc` | Any other value is a `422` |
| `limit` | int, `0 <= limit <= 100` | `20` | Above 100 is a **`422`, not a silent clamp** — a client paging with too large a limit should learn that it is, rather than quietly receive short pages. `limit=0` is valid and returns an empty `items` with the real `total` |
| `offset` | int, `>= 0` | `0` | Negative is a `422` |

```bash
curl 'http://localhost:8000/api/products?category=e-books&sort=price&direction=desc&limit=2'
```

```json
{
  "items": [
    {
      "id": "1",
      "name": "Deep Work: Rules for Focused Success",
      "priceMinor": 1499,
      "currency": "USD",
      "shortDescription": "A practical guide to cultivating deep, distraction-free focus.",
      "thumbnailUrl": "https://cdn.qbiq.dev/products/deep-work.jpg",
      "category": {"slug": "e-books", "name": "E-Books"}
    }
  ],
  "total": 12,
  "limit": 2,
  "offset": 0
}
```

`total` is the count matching the filter, not the length of `items` — it is what paging
controls need. `category` is always present on a listing row and never `null`, so a
listing page can render a category chip without a second request.

| Status | When |
|---|---|
| `200` | Query is valid (including a filter that matches nothing — `items: []`, `total: 0`) |
| `422` | Unknown `category` slug; `limit > 100` or `limit < 0`; `offset < 0`; `sort` or `direction` outside its enum |

---

## `GET /api/products/{productId}`

The detail page for one product: everything in a listing row, plus `longDescription` and
`reviews`.

```bash
curl http://localhost:8000/api/products/11
```

```json
{
  "id": "11",
  "name": "AWS for Backend Engineers: CDK in Practice",
  "priceMinor": 6499,
  "currency": "USD",
  "shortDescription": "Infrastructure as code on AWS using the Python CDK.",
  "thumbnailUrl": "https://cdn.qbiq.dev/products/aws-cdk-course.jpg",
  "category": {"slug": "online-courses", "name": "Online Courses"},
  "longDescription": "Hands-on modules building VPCs, ECS Fargate services, …",
  "reviews": [
    {"id": "20", "author": "Fatima Z.", "rating": 5,
     "body": "Took this straight into a real project the same week."}
  ]
}
```

`reviews` is an array, empty when the product has none. `rating` is an integer 1–5.

| Status | When |
|---|---|
| `200` | Product exists |
| `404` | No such product — **including a non-numeric id**. `/api/products/abc` is a `404`, not a `422`: the path parameter is typed `str` on purpose so an unknown id has one answer rather than two |

---

## `GET /api/categories`

Every category, for the catalogue's filter UI. Not paged.

```bash
curl http://localhost:8000/api/categories
```

```json
[
  {"slug": "e-books", "name": "E-Books"},
  {"slug": "online-courses", "name": "Online Courses"},
  {"slug": "software-licences", "name": "Software Licences"}
]
```

`slug` is what `GET /api/products?category=` expects; `name` is the display label. (The
database column is `category.label`; it is mapped to `name` at the storage boundary, so
`name` is what every layer above sees.)

| Status | When |
|---|---|
| `200` | Always |

---

## Cart

Four routes, exactly the operations [ADR-001](adr/ADR-001-server-owned-cart.md) assigns
to the server. All four return the **same** `CartView` body, so a client never has to
reconcile a partial response against local state:

```json
{
  "items": [
    {"productId": "11",
     "name": "AWS for Backend Engineers: CDK in Practice",
     "unitPriceMinor": 6499,
     "quantity": 2,
     "subtotalMinor": 12998}
  ],
  "totalMinor": 12998,
  "currency": "USD"
}
```

Facts that hold across all four:

- **Prices are never accepted from the client.** `unitPriceMinor` and `subtotalMinor`
  are re-resolved from the catalogue on every call; Redis stores only
  `{productId: quantity}`. A catalogue price change is visible in an existing Cart on
  the very next response, and a stale price cannot be served because none is stored.
- **`currency` on an empty Cart is `"USD"`** — a Cart has no currency of its own, so
  with no lines there is nothing to read one from, and every seeded product is USD.
- **A line whose product has vanished from the catalogue is dropped silently** from the
  rendered Cart rather than erroring, so one deleted product cannot lock a Shopper out
  of the rest of their Cart.
- **Request bodies reject unknown fields.** An extra key — say `unitPriceMinor` — is a
  `422`, not a value quietly ignored. This is what stops a client from believing it can
  set a price.
- **Quantity ceiling: 1000 per line**, enforced cumulatively on `POST` (existing +
  requested) and absolutely on `PATCH`. Exceeding it is a `422` with a plain-string
  `detail`, not a clamp.
- Both `productId` and `product_id` are accepted in a request body (the models populate
  by field name as well as alias), but camelCase is the documented form.

### `GET /api/cart`

Returns the current Shopper's Cart, creating an empty one — and minting a session — if
this is the first contact.

```bash
curl -c jar.txt http://localhost:8000/api/cart
```

```json
{"items": [], "totalMinor": 0, "currency": "USD"}
```

| Status | When |
|---|---|
| `200` | Always, including for a Shopper who has never had a Cart |

### `POST /api/cart/items`

Adds `quantity` of a product. If the line already exists, the quantity is **incremented**
rather than the line duplicated.

```bash
curl -b jar.txt -c jar.txt -X POST http://localhost:8000/api/cart/items \
  -H 'Content-Type: application/json' \
  -d '{"productId": "11", "quantity": 2}'
```

Body:

| Field | Type | Required | Notes |
|---|---|---|---|
| `productId` | string | yes | Must exist in the catalogue |
| `quantity` | int, `>= 1` | yes | `0` or negative is a `422` |

| Status | When |
|---|---|
| `200` | Added. Returns the whole Cart |
| `404` | `productId` is not in the catalogue — `{"detail": "Unknown product id: 'nope'"}` |
| `422` | `quantity < 1`; missing field; unknown extra field in the body; resulting line quantity would exceed 1000 |

### `PATCH /api/cart/items/{productId}`

Sets a line's quantity to exactly `quantity`.

```bash
curl -b jar.txt -c jar.txt -X PATCH http://localhost:8000/api/cart/items/11 \
  -H 'Content-Type: application/json' \
  -d '{"quantity": 3}'
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `quantity` | int, `>= 1` | yes | **`0` is a `422`, not a removal** |

`quantity: 0` is rejected deliberately. Removal is `DELETE`; allowing `PATCH 0` would
give clients a second spelling of delete to come to depend on. (The domain repository
underneath *does* accept `0`; the HTTP layer enforces the stricter floor.)

| Status | When |
|---|---|
| `200` | Quantity set. Returns the whole Cart |
| `404` | `productId` is not in the catalogue |
| `422` | `quantity < 1`; unknown extra field; `quantity > 1000` |

### `DELETE /api/cart/items/{productId}`

Removes a line.

```bash
curl -b jar.txt -c jar.txt -X DELETE http://localhost:8000/api/cart/items/11
```

| Status | When |
|---|---|
| `200` | Always — **removing a line that was never in the Cart is a no-op, not a `404`**. Delete is idempotent, so a double-click or a retry cannot produce a spurious error. Returns the resulting Cart |

---

## What is not here

There is no checkout, order, payment, user, or authentication endpoint. Checkout is
mocked entirely in the SPA and stores nothing; there are no accounts at all
([ADR-002](adr/ADR-002-no-authentication.md)).
