# qbiq_h — Mini E-Commerce

A storefront for digital goods: a Vue 3 SPA over a FastAPI service, with Postgres for
the catalogue and Redis for Sessions and Carts.

> - **What the words mean** — [`CONTEXT.md`](CONTEXT.md) is the glossary (Product, Cart,
>   Line Item, Shopper, Checkout). Nothing here re-defines them.
> - **Why it is built this way** — [`docs/adr/`](docs/adr). This README links to the
>   decisions rather than restating them.
> - **What is still to do** — [GitHub issues](https://github.com/yosefsha/qbiq_h/issues),
>   tracked from [#24](https://github.com/yosefsha/qbiq_h/issues/24).

---

## Quick start

One command, from a clean checkout, with Docker running:

```bash
docker compose --profile prod-like up --build
```

Then open **<http://localhost>** — port 80 by default, or whatever `WEB_PORT` you set
(see below).

That is the whole setup. There is no separate migration or seeding step: the `migrate`
service runs `alembic upgrade head && python -m app.seed` and exits, and `api` waits for
it to complete successfully, so the storefront comes up with a migrated, populated
catalogue (12 products across 3 categories) rather than an empty one. Both halves are
idempotent, so re-running `up` is safe.

### Ports

Every published port has a default and can be overridden from a `.env` file at the repo
root. Copy [`.env.example`](.env.example) and edit it — it lists every variable Compose
reads, and the stack runs with no `.env` present at all.

| Variable | Default | What it publishes |
|---|---|---|
| `WEB_PORT` | `80` | nginx serving the SPA (`prod-like`) |
| `VITE_PORT` | `5173` | Vite dev server (`dev`) |
| `API_PORT` | `8000` | FastAPI |
| `POSTGRES_PORT` | `5432` | Postgres |
| `REDIS_PORT` | `6379` | Redis |

If a default is already taken on your machine, move it. The machine this was last
verified on uses:

```dotenv
POSTGRES_PORT=55432
REDIS_PORT=56379
API_PORT=18000
WEB_PORT=8080
```

…which puts the storefront at <http://localhost:8080> and the API at
<http://localhost:18000>. Note that `WEB_PORT` and `VITE_PORT` also feed
`ALLOWED_ORIGINS` for the API container (see `docker-compose.yml`), so changing them
keeps CORS correct automatically.

---

## The two Compose profiles

`postgres`, `redis`, `migrate` and `api` carry no profile, so they start under either
one. The profile only picks how the SPA is served.

```bash
docker compose --profile prod-like up   # nginx + built SPA  -> http://localhost:${WEB_PORT:-80}
docker compose --profile dev up         # Vite + HMR         -> http://localhost:${VITE_PORT:-5173}
```

| Service | Profile | What it is |
|---|---|---|
| `postgres` | both | `postgres:16-alpine`, catalogue storage, volume `pgdata` |
| `redis` | both | `redis:7-alpine`, Sessions and Carts. Started with `--maxmemory-policy noeviction` deliberately: every key carries a TTL, so an LRU policy could evict Carts. The production form of that question is the open item in [ADR-003](docs/adr/ADR-003-managed-aws-data-tier.md) |
| `migrate` | both | Runs `alembic upgrade head && python -m app.seed`, then exits. Shares `api`'s image tag so schema and code can never drift |
| `api` | both | FastAPI on uvicorn with 4 workers; health-checked on `GET /health` |
| `web` | `prod-like` | nginx serving the built SPA and **path-routing `/api/` to `api:8000`** |
| `web-dev` | `dev` | `node:22-alpine` running `npm ci && npm run dev`, with Vite proxying `/api` to `http://api:8000` |

`prod-like` is the profile worth using by default, because it is the one that exercises
the real production shape: SPA and API on **one origin**, which is what keeps the
session cookie `SameSite=Lax` instead of forcing it to `None`
([ADR-001](docs/adr/ADR-001-server-owned-cart.md)). `dev` gets you hot module reload;
Vite's proxy reproduces the same single-origin illusion for the browser.

---

## Backend

Python 3.12 (the runtime image is `python:3.12-slim`). Everything below runs from
`backend/`.

### Without Docker

Postgres and Redis still have to come from somewhere — the simplest route is to leave
the two containers up (`docker compose up postgres redis`) and run the app on the host.

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt      # includes requirements.txt + pytest + httpx

export DATABASE_URL=postgresql://qbiq:qbiq@localhost:5432/qbiq_h
export REDIS_URL=redis://localhost:6379/0

alembic upgrade head                     # create the schema
python -m app.seed                       # load the catalogue (idempotent, silent on success)

uvicorn app.main:app --reload --port 8000
```

`requirements.txt` is runtime-only; `pytest` and `httpx` live in `requirements-dev.txt`
so they never reach the runtime image.

### Environment variables

Read once at import time by [`backend/app/settings.py`](backend/app/settings.py). Every
one has a local-development default, so `uvicorn app.main:app` boots with none of them
set.

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql://qbiq:qbiq@localhost:5432/qbiq_h` | Postgres connection string for the catalogue |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection string for Sessions and Carts |
| `COOKIE_SECURE` | `false` | `Secure` flag on the session cookie. Must be `false` over plain HTTP or the browser drops the cookie silently. Truthy values are `1`, `true`, `yes`, `on` (case-insensitive) |
| `ALLOWED_ORIGINS` | `http://localhost:5173` | Comma-separated CORS origins. A wildcard `*` is **rejected at startup** with a `ValueError`, and so is an empty list — `allow_credentials=True` forbids a wildcard |
| `CACHE_TTL_SECONDS` | `300` | Intended TTL for the product-query cache. **Currently unused**: no caching layer is implemented, so setting it changes nothing today |
| `SESSION_TTL_SECONDS` | `1800` | Sliding TTL on `session:{id}` and `cart:{id}` in Redis, and the cookie's `Max-Age` |
| `LOG_LEVEL` | `INFO` | Root log level for the JSON logger |

### Tests

```bash
cd backend
pytest -q
```

170 tests. Two things to know:

- **Database- and Redis-backed tests skip themselves rather than fail** when Postgres is
  unreachable, or reachable but un-migrated (`alembic upgrade head` not yet run). Run
  with `-rs` to see the skip reasons. With nothing running, the suite reports
  `1 failed, 127 passed, 42 skipped` — the one failure being the test in the next bullet.
  **In CI a skip is a failure** — see [Testing and CI](#testing-and-ci).
- **One test does not honour `REDIS_URL`.**
  `tests/test_session.py::test_ttl_is_refreshed_on_every_access` connects using
  `TEST_REDIS_URL` (or `TEST_REDIS_PORT`), defaulting to `redis://localhost:6379/0`, and
  it *fails* rather than skipping when nothing is listening there. If you moved
  `REDIS_PORT`, export the matching value:

  ```bash
  TEST_REDIS_PORT=56379 REDIS_URL=redis://localhost:56379/0 \
    DATABASE_URL=postgresql://qbiq:qbiq@localhost:55432/qbiq_h pytest -q
  ```

### Lint

Ruff is pinned in CI rather than in `requirements-dev.txt`, so install it explicitly:

```bash
cd backend
pip install ruff==0.16.2
ruff check .
```

---

## API

Base URL is `/api` (plus `/health`, which sits outside it because the ALB target group
probes it directly). Full request and response shapes, every query parameter, and every
error case are in **[docs/api.md](docs/api.md)**.

| Method | Path |
|---|---|
| `GET` | `/health` |
| `GET` | `/api/products` |
| `GET` | `/api/products/{productId}` |
| `GET` | `/api/categories` |
| `GET` | `/api/cart` |
| `POST` | `/api/cart/items` |
| `PATCH` | `/api/cart/items/{productId}` |
| `DELETE` | `/api/cart/items/{productId}` |

Two conventions run through all of it:

- **Money is integer minor units plus a currency code** — `priceMinor: 1499` with
  `currency: "USD"` is $14.99. Never a float, anywhere, in storage or on the wire, so
  cart totals are exact integer addition with nothing to round
  ([ADR-003](docs/adr/ADR-003-managed-aws-data-tier.md)).
- **camelCase on the wire, snake_case in Python** — `priceMinor`, `shortDescription`,
  `productId`, `totalMinor`.

The live schema is at `/openapi.json`, with Swagger UI at `/docs`. Note that the
generated schema lists only `200` and `422` for most routes; the `404`s documented in
`docs/api.md` are raised by hand and verified by curl, not declared in the OpenAPI
`responses`.

---

## Frontend

Vue 3 + TypeScript + Vite + Pinia + Tailwind, in `frontend/`. Node 22 (matching the
`node:22-alpine` build image).

```bash
cd frontend
npm ci            # lockfile is the input; `npm install` is not equivalent
npm run dev       # Vite dev server on :5173, proxying /api and /health
npm run build     # vue-tsc -b && vite build  ->  dist/
npm run test      # vitest run — 113 tests in 15 files
npm run lint      # eslint . --max-warnings 0
```

(`npm run preview` and `npm run test:watch` also exist; see `package.json`.)

`npm run dev` alone assumes the API is on `http://localhost:8000`. If yours is
elsewhere, point the proxy at it:

```bash
VITE_DEV_PROXY_TARGET=http://localhost:18000 npm run dev
```

| Variable | Default | Purpose |
|---|---|---|
| `VITE_API_BASE_URL` | `/api` | Prefix the API client puts on every request path. Same-origin by default, because the SPA and API share an origin in production |
| `VITE_DEV_PROXY_TARGET` | `http://localhost:8000` | Where the Vite dev server proxies `/api` and `/health`. Build-time/dev-server only — read in `vite.config.ts`, not in application code. The Compose `dev` profile sets it to `http://api:8000` |

`frontend/.env.example` documents `VITE_API_BASE_URL`. Every request goes through the
single `apiClient` wrapper in `src/api/client.ts`, which sets `credentials: 'include'`
so the anonymous session cookie is attached — no component or store calls `fetch`
directly.

Routes: `/` (catalogue), `/products/:id` (detail), `/cart`, and a catch-all
not-found page.

---

## Architecture

The short version: the browser talks to **one origin**. `/api/*` is path-routed to the
backend behind that same origin — nginx locally, a CloudFront cache behavior in AWS —
rather than living on its own subdomain, and that is what lets the session cookie stay
`SameSite=Lax`.

Diagram, request paths, and the VPC boundary: **[docs/architecture.md](docs/architecture.md)**.

---

## Deploying

Infrastructure is AWS CDK (Python) in `infra/`, driven by `cdk.json` at the repo root.

```bash
python3 -m venv .venv && .venv/bin/pip install -r infra/requirements.txt
source .venv/bin/activate
cdk synth -c env=staging     # or -c env=prod
```

`cdk synth` succeeds offline today. **Nothing has ever been deployed**, and several
things must be replaced before `cdk deploy` can work at all — the fake hosted zone, the
CodeStar connection, an empty ECR. The full list, plus secrets rotation and log reading:
**[docs/runbook.md](docs/runbook.md)**.

---

## Testing and CI

[`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs on every PR to `main`, every
push to `main`, and on `workflow_dispatch`. Three jobs, in parallel:

1. **`backend` — ruff + pytest.** Spins up real `postgres:16-alpine` and `redis:7-alpine`
   service containers (same images and health probes as `docker-compose.yml`), runs
   `ruff check .`, waits for both services to actually accept connections, runs
   `alembic upgrade head`, then `pytest -q -rs`.
   **A skipped test fails this job**: the step greps the output for `N skipped` and exits
   1 if it finds any. The database-backed fixtures skip themselves when the schema is
   missing, which is right on a laptop and wrong in CI — it would let a broken repository
   through green — so the migration step above removes any legitimate reason to skip and
   this gate enforces it.
2. **`frontend` — eslint + vue-tsc + vitest + build.** `npm ci`, `npm run lint`
   (`--max-warnings 0`, without which nothing could ever fail the gate), `npx vue-tsc -b
   --force` as its own step so a type error is reported as one, `npm run test`,
   `npm run build`.
3. **`images` — docker build.** Builds both Dockerfiles to prove they still build.
   Nothing is pushed.

A second workflow, `.github/workflows/code-review.yml`, is separate from this gate.

Coding standards for both stacks — structure, style, testing, build commands — are in
[`docs/coding-instructions.md`](docs/coding-instructions.md).

---

## Known gaps

Stated plainly, because a README that describes intent as though it were reality is
worse than none:

- **No authentication.** Shoppers are anonymous; there is no login, registration, or
  account. Deliberate, with the cost and the consequences written up in
  [ADR-002](docs/adr/ADR-002-no-authentication.md).
- **Checkout is a mock and no order is stored.** The button lives entirely in the SPA
  (`src/stores/cart.ts`); there is no checkout or order endpoint, no payment, and no
  order history. Per [`CONTEXT.md`](CONTEXT.md), that is what Checkout *means* here.
- **No caching layer.** `CACHE_TTL_SECONDS` is parsed into settings and read by nothing.
  Every product query goes to Postgres.
- **No data stack in CDK.** `infra/stacks/data_stack.py` does not exist yet (INF-04), so
  no deployable RDS or ElastiCache is defined, and the ECS task definition injects no
  `DATABASE_URL` or `REDIS_URL`. See the runbook.
- **Nothing is deployed.** Local Docker Compose is the only environment that has ever
  run.
