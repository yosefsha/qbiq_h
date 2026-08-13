
# short video:




https://github.com/user-attachments/assets/bcc188bd-1c87-4310-ab04-5d086e033b44




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
docker compose up --build
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
| `WEB_PORT` | `80` | nginx serving the SPA |
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

## Services and the `dev` profile

Everything below starts by default. Only `web-dev` sits behind a profile.

```bash
docker compose up                  # the storefront -> http://localhost:${WEB_PORT:-80}
docker compose up web-dev          # Vite + HMR     -> http://localhost:${VITE_PORT:-5173}
```

Naming `web-dev` explicitly enables its profile and pulls in only its dependencies, so
you get the dev server without also running nginx. `docker compose --profile dev up`
runs both, which is occasionally useful for comparing them.

| Service | Profile | What it is |
|---|---|---|
| `postgres` | default | `postgres:16-alpine`, catalogue storage, volume `pgdata` |
| `redis` | default | `redis:7-alpine`, Sessions and Carts. Started with `--maxmemory-policy noeviction` deliberately: every key carries a TTL, so an LRU policy could evict Carts. The production form of that question is the open item in [ADR-003](docs/adr/ADR-003-managed-aws-data-tier.md) |
| `migrate` | default | Runs `alembic upgrade head && python -m app.seed`, then exits. Shares `api`'s image tag so schema and code can never drift |
| `api` | default | FastAPI on uvicorn with 4 workers; health-checked on `GET /health` |
| `web` | default | nginx serving the built SPA and **path-routing `/api/` to `api:8000`** |
| `web-dev` | `dev` | `node:22-alpine` running `npm ci && npm run dev`, with Vite proxying `/api` to `http://api:8000` |

nginx is the default because it is the shape that matches production: SPA and API on
**one origin**, which is what keeps the session cookie `SameSite=Lax` instead of forcing
it to `None` ([ADR-001](docs/adr/ADR-001-server-owned-cart.md)). It was previously behind
a `prod-like` profile, which meant a plain `docker compose up` started an API with no
storefront in front of it. `web-dev` gets you hot module reload; Vite's proxy reproduces
the same single-origin illusion for the browser.

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

### Sessions and how long a Cart lives

Shoppers are anonymous ([ADR-002](docs/adr/ADR-002-no-authentication.md)). The first
request that touches a Cart mints an opaque `secrets.token_urlsafe(32)` token and returns
it as an `HttpOnly; SameSite=Lax` cookie; the Cart itself lives server-side in Redis under
`cart:{sessionId}` ([ADR-001](docs/adr/ADR-001-server-owned-cart.md)).

**A Cart survives 30 minutes of inactivity** (`SESSION_TTL_SECONDS`, default `1800`), and
the window **slides**. It is not a countdown from when an item was added: `session:{id}`,
`cart:{id}` and the cookie's `Max-Age` all carry the same TTL, and it is refreshed on
every request that touches the Cart — **including a read**. Opening the cart page is as
much "activity" as changing a quantity, so a Shopper who is only looking at their Cart
does not have it expire out from under them.

A Cart ends in one of four ways:

| | what happens |
|---|---|
| **30 minutes idle** | Redis expires `cart:{id}` and `session:{id}`; the cookie lapses with them, so the next visit starts a fresh, empty Cart rather than pointing at a Cart that is gone |
| **Emptied by hand** | the key is `DEL`-ed once the last line is removed, rather than storing an empty map |
| **Checkout** | the mock checkout issues a real `DELETE` per line, so the **server-side Cart is genuinely cleared** — it is not a client-only illusion that leaves a stale Cart in Redis |
| **A product leaves the catalogue** | that line is dropped when the Cart is rendered; the rest of the Cart is unaffected |

What will *not* end a Cart is memory pressure: Redis runs `maxmemory-policy noeviction`
precisely because every key here carries a TTL, so a `volatile-*` policy would treat live
Carts as eviction candidates alongside cache entries. A full node refuses writes loudly
instead of discarding a Shopper's Cart quietly.

### Tests

```bash
cd backend
pytest -q
```

209 tests, all passing with Postgres and Redis up. Two things to know:

- **Database- and Redis-backed tests skip themselves rather than fail** when Postgres is
  unreachable, or reachable but un-migrated (`alembic upgrade head` not yet run). Run
  with `-rs` to see the skip reasons. With nothing running the suite reports
  `3 failed, 155 passed, 51 skipped`; the failures are Redis-backed and go away once it
  is reachable — see the next bullet for the one that needs a variable rather than a
  running service. **In CI a skip is a failure** — see [Testing and CI](#testing-and-ci).
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
npm run test      # vitest run — 143 tests in 17 files
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

## Design decisions

The four that were costly to reverse are written up as ADRs. Each records what was
chosen, what was rejected, and what the choice costs — the cost is the part worth
reading:

| ADR | Decision | The trade |
|---|---|---|
| [001](docs/adr/ADR-001-server-owned-cart.md) | **The Cart is server-owned**, in Redis under `cart:{sessionId}` with a sliding TTL; Pinia mirrors the server's response rather than owning the Cart | The brief asked for both Pinia state *and* Cart endpoints, which leaves two possible homes for the truth. Server-authoritative means totals cannot be tampered with client-side, at the price of a round trip per mutation |
| [002](docs/adr/ADR-002-no-authentication.md) | **No accounts.** The session cookie identifies an anonymous Shopper for the sole purpose of owning a Cart | A deliberate omission, not an oversight — and it is why Cart merge-on-login is the hard part of adding auth later |
| [003](docs/adr/ADR-003-managed-aws-data-tier.md) | **RDS Postgres + ElastiCache Redis**, not a JSON mock store | The brief allows a file; real engines mean dev/prod parity and a schema, at the cost of managed-service spend and a migration path |
| [004](docs/adr/ADR-004-github-actions-over-codepipeline.md) | **GitHub Actions over OIDC**, not CodePipeline + CodeBuild | A deliberate divergence from `CLAUDE.md`, written down rather than substituted quietly. No stored AWS credential; the cost is that the workflow cannot reach a private subnet, so migrations run as ECS tasks |

Decisions that did not need an ADR but explain the code:

- **One origin, everywhere.** `/api/*` is path-routed to the backend — nginx locally, a
  CloudFront behavior in AWS — rather than living on a subdomain. That is what keeps the
  session cookie `SameSite=Lax` instead of forcing it to `None`, and why there is no CORS
  configuration in production.
- **Prices are integer minor units plus a currency code**, never floats. Cart totals are
  exact integer arithmetic, and no rounding has to be undone if payment is ever added.
- **Filtering, sorting and paging are server-side**, in SQL. The client sends a query, not
  a filter over a fetched array, so the catalogue can outgrow one page without a rewrite.
- **Redis runs `maxmemory-policy noeviction`.** Every key carries a TTL, so a `volatile-*`
  policy would evict live Carts alongside cache entries. A full node refuses writes loudly
  rather than discarding state silently.
- **The Cart's TTL slides on reads, not just writes.** A Shopper looking at their Cart is
  active, so a read refreshes the 30-minute window rather than letting it run out
  mid-session. See [Sessions and how long a Cart lives](#sessions-and-how-long-a-cart-lives).
- **The cache is a decorator, not a branch.** `CachedProductRepository` wraps
  `SqlProductRepository` behind the same interface, so caching is composed in `deps.py`
  and neither the API nor the SQL layer knows it exists.
- **Errors are a typed result, not exceptions.** The API client returns
  `ApiResult<T>`, so every call site has to handle the failure branch to compile —
  network, HTTP and parse failures are distinguished rather than collapsed.

---

## Deploying

> ### Live: **<https://qbiq.yossidemo.click>**
>
> Staging, on the account below, served by CloudFront over HTTPS with an ACM certificate
> and a Route 53 alias — both created by `infra/stacks/frontend_stack.py`, neither by
> hand. The API is the same origin: `/api/*` is a cache behavior pointing at the ALB, so
> there is no second hostname and no CORS in production.

Infrastructure is AWS CDK (Python) in `infra/`, driven by `cdk.json` at the repo root.

```bash
python3 -m venv .venv && .venv/bin/pip install -r infra/requirements.txt
source .venv/bin/activate
cdk synth -c env=staging     # or -c env=prod
```

Standing an environment up is one command:

```bash
./scripts/deploy-to-aws.sh staging      # or prod; staging is the default
./scripts/destroy-aws.sh staging        # cdk destroy in reverse, behind a typed prompt
```

It deploys the ECR stack, builds and pushes the backend image, deploys the rest of the
stacks, runs `alembic upgrade head` and `python -m app.seed` as one-off Fargate tasks
inside the VPC, uploads the SPA to S3, invalidates CloudFront, forces a new ECS
deployment, and prints the URL to open. It is re-runnable: a second run is an update, not
an error.

Two things worth knowing before reading the script:

- **The ECR repository is its own stack (`<env>-ecr`), deployed before everything else.**
  The backend's task definitions pull `<repo>:latest`, so an image has to exist between
  the registry being created and the ECS service trying to start — otherwise the service
  never stabilises and CloudFormation rolls the deploy back.
- **The image is built `--platform linux/amd64`, and that is not optional.** Fargate here
  is x86_64; an image built natively on Apple Silicon runs fine locally and dies in ECS
  with `exec format error`.
- **There is no NAT Gateway, and staging runs one task.** ~$38/month cheaper, and both
  choices cost something real: the ECS tasks run in public subnets with public IPs (the
  only way to reach ECR without a NAT), automatic rotation of the RDS secret is gone with
  the egress it needed, and one task means no AZ redundancy in staging. A public IP is
  **not** public access — the task security group still admits inbound from the ALB alone,
  and RDS and Redis are in isolated subnets with no route to the internet. The full
  trade-off table, and how to reverse any of it, is in
  [docs/runbook.md](docs/runbook.md).

**Staging has been deployed and torn down repeatedly from this script**, which is what
the teardown settings are for: in staging the RDS instance, the ElastiCache group, the
ECR repository and the SPA bucket are all destroyed with the stack, so a redeploy starts
clean rather than colliding with a retained resource. Production keeps every one of them.
What each step does by hand, secrets rotation and log reading: **[docs/runbook.md](docs/runbook.md)**.

Deploys of *already-standing* environments are meant to run from
[`.github/workflows/deploy.yml`](.github/workflows/deploy.yml) on merge to `main`,
assuming an AWS role through GitHub's OIDC provider — there is no CodePipeline and no
stored AWS credential. The workflow deliberately cannot create infrastructure, which is
why the script above exists alongside it. Why, and what that costs, is in
[ADR-004](docs/adr/ADR-004-github-actions-over-codepipeline.md). **That workflow has
never completed a deploy** — see Future development below for exactly what blocks it.

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
- **Staging is deployed; production is not.** `scripts/deploy-to-aws.sh staging` has run
  against a real account, and staging is deliberately minimal — one task, a single-node
  Redis with no failover, no RDS backups, and every resource set to be destroyed with the
  stack. None of the production stacks have ever been created.

## Future development

Things this project would need before it were more than a demo, kept here rather than in
issues because each is a known consequence of a deliberate shortcut, not an open task
somebody is working:

- **A GitHub Actions deploy has never succeeded, and cannot yet.** The workflow's gate
  fails on the first prerequisite: `AWS_ACCOUNT_ID` is unset as a repository variable. A
  push to `main` also resolves the target to `production` ([`deploy.yml:89`](.github/workflows/deploy.yml)),
  and no production stack exists to deploy into. `scripts/deploy-to-aws.sh` is the only
  path that has ever worked end to end.
- **The Actions deploy runs migrations but never seeds.** `deploy.yml` runs
  `alembic upgrade head` as a one-off task and stops there, while
  `scripts/deploy-to-aws.sh` runs the migration *and* `python -m app.seed`. An
  environment first deployed by Actions would come up with an empty catalogue and no
  error to explain it. Either the workflow grows a seed step or seeding moves into the
  migration task's command.
- **Uploaded media needs its own bucket, and there is no upload path yet.** Product
  imagery is twelve generated placeholders today
  (`scripts/generate_thumbnails.py` → `frontend/public/assets/thumbnails/`), which ship
  inside the frontend build and are rebuilt from the repository on every deploy. Real
  imagery — anything an admin *uploads* rather than the repository *generates* — cannot
  work that way, and the reason is one command:

  ```bash
  aws s3 sync frontend/dist/ "s3://$BUCKET/" --delete    # deploy-to-aws.sh:443, deploy.yml:408
  ```

  `--delete` makes the bucket an exact mirror of `frontend/dist/`, so anything in it that
  the build did not produce is removed — on **every deploy**, not merely on teardown, and
  no `RemovalPolicy` affects that. `--delete` is not gratuitous: Vite emits
  content-hashed filenames, so without it every chunk of every past build accumulates
  forever.

  Two half-measures exist and neither is the answer. Syncing into a prefix
  (`s3://$BUCKET/app/`) scopes the delete correctly but needs a matching CloudFront
  `origin_path`, which then prefixes *every* request through that origin. Adding
  `--exclude` to both syncs works only while the excluded files live outside `dist/`, has
  to be duplicated in two files, and is one tidy-up away from deleting the whole image
  library.

  **The shape this wants is a second bucket**, because build output and uploaded media
  differ in every property that matters:

  | | SPA bucket | media bucket |
  |---|---|---|
  | source of truth | a git commit | the upload itself — it exists nowhere else |
  | deploy behaviour | strict `--delete` mirror | never synced, never mirrored |
  | who writes | CI / the deploy script | the admin app, at runtime |
  | removal policy | destroy freely, rebuild with `npm run build` | retain; losing it loses the catalogue's imagery |

  The write path is the sharpest of those. An admin app needs `s3:PutObject`, and
  granting that on the bucket serving the SPA means a compromised upload path can replace
  `index.html` — stored XSS on every visitor. A separate bucket keeps that permission
  nowhere near the JavaScript people execute.

  Serving it stays single-origin (so [ADR-001](docs/adr/ADR-001-server-owned-cart.md) is
  untouched): a second S3 origin with OAC on the same distribution, plus one behavior on
  a distinct path — `/media/*` rather than sharing `/assets/*`, so uploaded files and
  Vite's hashed output can never collide. `Product.thumbnail_url` already holds a plain
  root-relative string, so pointing it at `/media/…` needs no API or schema change.

  At that point the imagery also leaves git: hundreds of uploaded photos do not belong in
  a repository, and once they are not in the repository they cannot be in `dist/` — which
  is what lets the SPA bucket stay a strict mirror rather than something with exceptions
  carved into it.
- **A write path would need cache invalidation.** The catalogue cache expires by TTL
  alone, which is correct while the API is read-only: nothing can go stale except a
  reseed. The first endpoint that edits a product has to invalidate
  `products:id:{id}` and the listing keys alongside the write.
- **Authentication.** There is none, deliberately —
  [ADR-002](docs/adr/ADR-002-no-authentication.md) — and the Cart is bound to an
  anonymous session cookie instead. Adding accounts is not a bolt-on: the Cart is keyed
  by session id in Redis ([ADR-001](docs/adr/ADR-001-server-owned-cart.md)), so a login
  has to **merge** the anonymous Cart into the user's on sign-in, or a shopper loses what
  they were holding at the moment they authenticate. The rest is conventional — an OIDC
  provider (Cognito, Auth0) over the existing single origin, so the session cookie
  mechanism and `SameSite=Lax` survive unchanged; a `user` table with the Cart's owner
  becoming a user id where one exists; and authorization on every write path, which today
  needs none because there is nothing a shopper can mutate but their own Cart.
- **Payment, and orders that actually exist.** Checkout is a mock that clears the Cart
  client-side; there is no order, no payment and no record afterwards, which is what
  Checkout *means* in [`CONTEXT.md`](CONTEXT.md) today. Making it real is mostly the
  parts that are not the payment call: an `order` table capturing prices **as they were
  at purchase** rather than joining to a live catalogue, a hosted-checkout redirect
  (Stripe Checkout or similar) so no card data ever reaches this service or its PCI
  scope, an idempotency key so a double-submitted checkout cannot charge twice, and a
  **webhook** as the source of truth for payment success — the browser returning from the
  provider is not proof of anything. Prices are already integer minor units plus a
  currency code, so the arithmetic is exact and no float rounding has to be undone first.
- **The seed reconciles `thumbnail_url` and nothing else.** Re-seeding repairs that one
  field on existing rows; prices, descriptions and reviews are left as they are. A real
  catalogue would need a considered upsert policy rather than one field's worth of
  special case.
- **RDS secret rotation is manual.** Removing the NAT Gateway left the rotation Lambda
  without egress to the Secrets Manager API, so automatic rotation was removed. See
  `data_stack.py` and the runbook.
