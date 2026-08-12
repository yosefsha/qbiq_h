# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Coding Instructions

See [docs/coding-instructions.md](docs/coding-instructions.md) for full coding standards covering Python/FastAPI and Vue/TypeScript — project structure, code style, testing, and build commands.

## Project Documentation

Three artifacts, each owning a different kind of fact. Nothing is duplicated between them — when you need to record something, pick the one place it belongs.

| Artifact | Holds | Example |
|---|---|---|
| [CONTEXT.md](CONTEXT.md) | **The language** — what domain terms mean | What a Cart, a Line Item, or a Shopper *is* |
| [docs/adr/](docs/adr) | **The why** — decisions that are costly to reverse | Why the Cart is server-owned; why no auth |
| GitHub issues | **The what** — the work itself | The contract `SqlProductRepository` must satisfy |

### Task tracking (GitHub issues)

Every task is a GitHub issue on [`yosefsha/qbiq_h`](https://github.com/yosefsha/qbiq_h/issues). **[Issue #24](https://github.com/yosefsha/qbiq_h/issues/24) is the tracking issue** and holds the full checklist with the dependency order.

**Titles carry a stable ID** — `[BE-04] SqlProductRepository`. Issue numbers aren't known until creation, so dependencies between tasks are expressed with these IDs, not `#N`. Prefixes are `BE` (backend), `FE` (frontend), `INF` (platform), `DOC` (documentation).

**Every issue body has the same five sections:**

- **Goal** — one sentence on what the task achieves.
- **Contract** — the interface, endpoint shape, or schema this task promises. This is the section that makes tasks independent: a downstream task codes against the contract and can start before the upstream task is finished. Treat it as binding — if you need to change a contract, say so on the issue, because other tasks are built on it.
- **Out of scope** — explicit non-goals, which stop adjacent issues from bleeding into each other.
- **Done when** — objectively verifiable checkboxes.
- **Verify** — the literal command that proves the task is complete.

Plus a `Depends on:` line and links to any ADR that constrains the work.

**Labels:** `area:backend`, `area:frontend`, `area:infra`, `area:docs`.

**Working a task:** read the issue and `CONTEXT.md` — you should not need to read another task's code. Where an issue links an ADR, that ADR is a constraint, not a suggestion; if you find yourself wanting to violate it, raise it rather than quietly diverging. Tick `Done when` boxes as you go, so an interrupted session can be resumed from the issue alone. If a task turns out to need a decision that is hard to reverse, write a new ADR before continuing.

```bash
gh issue list --repo yosefsha/qbiq_h --label area:backend
gh issue view 4 --repo yosefsha/qbiq_h
```

## Infrastructure & Configuration (AWS + Python CDK)

All configuration below is production-grade. Infrastructure is defined as code using **AWS CDK (Python)**.

> **Current state:** INF-03 is done — `cdk.json` at the repo root points the CLI at `infra/app.py`, dependencies are pinned in `infra/requirements.txt`, and `cdk synth -c env=staging` / `-c env=prod` both succeed. `infra/` holds `app.py` and six stacks (network, data, ecr, backend, frontend, deploy); INF-04 added the data stack, INF-07 replaced the pipeline stack with the deploy stack ([ADR-004](docs/adr/ADR-004-github-actions-over-codepipeline.md)), and the ECR repository was later split out of the backend stack so a brand-new environment can be deployed at all. The hand-seeded context lookups in `cdk.json` are gone: availability zones now resolve live against the account and are cached in `cdk.context.json`, and the forged hosted-zone entry was deleted — `HostedZone.from_lookup` only runs when `custom_domain_enabled` is True, which it is not in either environment.
>
> ```bash
> python3 -m venv .venv && .venv/bin/pip install -r infra/requirements.txt
> source .venv/bin/activate
> cdk synth -c env=staging
> ```

### CDK Project Structure
```
infra/
  app.py              # CDK app entry point
  stacks/
    __init__.py
    network_stack.py   # VPC, subnets, security groups
    data_stack.py      # RDS Postgres + ElastiCache for Redis
    ecr_stack.py       # The container registry, alone so it can be deployed first
    backend_stack.py   # ECS/Fargate service for FastAPI
    frontend_stack.py  # S3 + CloudFront for Vue SPA
    deploy_stack.py    # GitHub OIDC provider + the deploy role Actions assumes
  config/
    prod.py            # Production environment config
    staging.py         # Staging environment config

scripts/
  deploy-to-aws.sh     # One-command deploy of a whole environment
  destroy-aws.sh       # cdk destroy in reverse order
```

**`<env>-ecr` is deployed before everything else, and an image is pushed between it and
`<env>-backend`.** The backend's service and migration task definitions both reference
`<repo>:latest`; a registry created by the same stack that consumes it is empty at the
moment the ECS service tries to pull, so the service never stabilises and CloudFormation
rolls the whole deploy back. `scripts/deploy-to-aws.sh` performs that order.

### Backend (FastAPI on ECS Fargate)
- Deploy as a Docker container on **ECS Fargate** behind an **ALB**.
- Dockerfile: multi-stage build — `python:3.12-slim` base, install from locked `requirements.lock`, run with `uvicorn --workers 4 --host 0.0.0.0 --port 8000`.
- ALB health check targets `GET /health`.
- Auto-scaling: target 70% CPU utilization, min 2 / max 10 tasks.
- Logs to **CloudWatch Logs** with 30-day retention.
- Secrets (DB credentials, API keys) stored in **AWS Secrets Manager**, injected as environment variables via ECS task definition — never baked into images.
- Use **ECR** for container image registry.

### Data Tier (RDS + ElastiCache)
See [ADR-003](docs/adr/ADR-003-managed-aws-data-tier.md) for the reasoning.
- Catalogue (products, categories, reviews) in **RDS for PostgreSQL** — private subnets, no public access, encrypted storage, automated backups, subnet group across 2+ AZs.
- Sessions, Carts, and the product-query cache in **ElastiCache for Redis** (Redis/Valkey engine — **not Memcached**, which has no replication or failover and would silently lose Carts on node loss).
- Both reachable only from the ECS task security group. Never from the internet.
- Credentials generated into **Secrets Manager** and injected at task start.
- Prices are stored and transported as **integer minor units** plus a currency code — never floats, so cart totals are exact integer arithmetic.
- ElastiCache runs `maxmemory-policy noeviction` with `reserved-memory-percent 25`, because every key carries a TTL and a `volatile-*` policy would evict Carts alongside cache entries. A full node refuses writes loudly instead of discarding state silently; a memory alarm at 75% is the signal to resize or to split cache from state. Resolved in INF-04 — see [ADR-003](docs/adr/ADR-003-managed-aws-data-tier.md).

### Frontend (Vue SPA on S3 + CloudFront)
- `npm run build` output deployed to an **S3 bucket** (private, no public access).
- **CloudFront** distribution with OAC (Origin Access Control) to serve from S3.
- Custom domain via **Route 53** alias record to CloudFront.
- **ACM certificate** in `us-east-1` for HTTPS.
- Cache policy: immutable assets (`/assets/*`) cached 1 year; `index.html` cached 0 seconds (always revalidated).
- Enable CloudFront Functions or Lambda@Edge for SPA routing (return `index.html` for 404s).
- **An `/api/*` cache behavior routes to the ALB**, forwarding cookies and query strings. This keeps the SPA and API on one origin, which is what allows the session cookie to stay `SameSite=Lax` rather than being weakened to `None` ([ADR-001](docs/adr/ADR-001-server-owned-cart.md)). Note S3 and CloudFront are edge services and are **not** in the VPC — only ECS, RDS, and ElastiCache share that boundary.

### CI/CD (GitHub Actions + OIDC)

See [ADR-004](docs/adr/ADR-004-github-actions-over-codepipeline.md) for why this is GitHub Actions and not CodePipeline + CodeBuild, and for what is lost by it.

- **Test gate:** `.github/workflows/ci.yml` — ruff, pytest against real Postgres and Redis, eslint, `vue-tsc`, vitest, and a build of both images. It runs on every pull request and every push to `main`, and it is the *only* place the suite runs.
- **Deploy:** `.github/workflows/deploy.yml`, on push to `main` and on `workflow_dispatch` (which takes a `target` of `production` or `staging`). Three jobs:
  - `gate` — resolves the target and blocks until `ci.yml` has concluded `success` for this exact commit. Nothing deploys otherwise, and the suite is not re-run here.
  - `backend` — build the image, tag it with the **commit SHA**, push to ECR; register a task-definition revision pinned to that tag; run `alembic upgrade head` as a **one-off ECS task** in the private subnets with the task security group, wait for it to stop and fail on a non-zero container exit code; then update the ECS service to the new revision (rolling, `minimumHealthyPercent: 100` / `maximumPercent: 200`, waiting for stability).
  - `frontend` — `npm ci && npm run lint && npm run build`, `aws s3 sync dist/ --delete`, CloudFront invalidation on `/*`.
- **Backend and frontend deploy independently** — neither job `needs` the other.
- **Production gate:** the deploy jobs declare a GitHub `environment`, which is where the required-reviewer rule lives. The workflow declares it; **a human must configure its reviewers and its deployment-branch policy in repository settings** — see `docs/runbook.md`.
- **No AWS credential is stored anywhere.** `permissions: id-token: write` gets a short-lived OIDC token; `infra/stacks/deploy_stack.py` holds the `token.actions.githubusercontent.com` provider and a least-privilege role whose trust is scoped to this repository and one GitHub environment, and whose policy names this environment's ECR repository, ECS service, task roles, bucket and distribution — never `*`.
- The workflow reads the cluster, service, task-definition families, subnets, security group, bucket and distribution id from the deploy stack's `CfnOutput`s at run time. No ARN is hardcoded in YAML.
- Migrations run from the image being deployed, never from the runner: a GitHub-hosted runner cannot reach RDS in a private subnet, and this is the only thing in the project that needed CodeBuild's VPC attachment.

### Networking
- **VPC** with public and **private isolated** subnets across 2+ AZs.
- **No NAT Gateway.** It was ~$32/month before any data passed through it — the largest single line item in a demo environment — so it was removed, and with it the `PRIVATE_WITH_EGRESS` subnets.
- ALB **and ECS tasks** in the public subnets; tasks carry a public IP (`assign_public_ip=True`). That is how they reach ECR, Secrets Manager and CloudWatch Logs at task start without a NAT. **A public IP is not public access**: the task security group admits inbound from the ALB security group on port 8000 and nothing else, so the ALB is still the only ingress path.
- RDS and ElastiCache stay in the **private isolated** subnets — no route to an internet gateway at all — reachable only from the ECS task security group.
- Rejected alternative, so it is not "fixed" later: interface VPC endpoints for ECR (api + dkr), Secrets Manager and CloudWatch Logs cost ~$7.20/month each, so four is ~$29/month against the NAT's ~$32 — the same bill with more moving parts.
- **What this costs:** the RDS secret's managed rotation Lambda needs egress to the Secrets Manager API and no longer has any, so automatic rotation is removed and rotation is manual. See `data_stack.py` and `docs/runbook.md`.
- Security groups: ALB allows inbound 443 only; ECS tasks allow inbound from ALB security group on port 8000 only.

### Monitoring & Observability
- **CloudWatch Alarms**: ALB 5xx rate > 1%, ECS CPU > 80%, unhealthy host count > 0.
- **SNS topic** for alarm notifications (email/PagerDuty).
- Structured JSON logging from FastAPI (use `python-json-logger`).
- **X-Ray** tracing on ALB and ECS for request tracing.

### Environment Configuration
- All environment-specific values (domain names, instance counts, feature flags) defined in `infra/config/` Python files — not hardcoded in stacks.
- CDK stacks accept an `env_config` parameter to swap between staging and production.
- Tag all resources with `Environment`, `Service`, and `Owner` tags.
- Enable **CDK Nag** (`cdk-nag`) as an App-level Aspect, so a rule violation fails `cdk synth` rather than review. Every suppression carries a written reason in the stack that owns it.
