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

> **Current state:** `infra/` holds `app.py` and four stacks, but no `cdk.json` — the file that points the CDK CLI at `infra/app.py` and is required for any `cdk` command. Nothing here has ever synthesized. Issue INF-03 closes that gap; do not assume any of the infrastructure below exists yet.

### CDK Project Structure
```
infra/
  app.py              # CDK app entry point
  stacks/
    __init__.py
    network_stack.py   # VPC, subnets, security groups
    data_stack.py      # RDS Postgres + ElastiCache for Redis (not yet written — see INF-04)
    backend_stack.py   # ECS/Fargate service for FastAPI
    frontend_stack.py  # S3 + CloudFront for Vue SPA
    pipeline_stack.py  # CodePipeline CI/CD
  config/
    prod.py            # Production environment config
    staging.py         # Staging environment config
```

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
- **Open:** ElastiCache is evictable and every key carries a TTL, so a `volatile-*` policy can evict Carts alongside cache entries. Resolve in INF-04.

### Frontend (Vue SPA on S3 + CloudFront)
- `npm run build` output deployed to an **S3 bucket** (private, no public access).
- **CloudFront** distribution with OAC (Origin Access Control) to serve from S3.
- Custom domain via **Route 53** alias record to CloudFront.
- **ACM certificate** in `us-east-1` for HTTPS.
- Cache policy: immutable assets (`/assets/*`) cached 1 year; `index.html` cached 0 seconds (always revalidated).
- Enable CloudFront Functions or Lambda@Edge for SPA routing (return `index.html` for 404s).
- **An `/api/*` cache behavior routes to the ALB**, forwarding cookies and query strings. This keeps the SPA and API on one origin, which is what allows the session cookie to stay `SameSite=Lax` rather than being weakened to `None` ([ADR-001](docs/adr/ADR-001-server-owned-cart.md)). Note S3 and CloudFront are edge services and are **not** in the VPC — only ECS, RDS, and ElastiCache share that boundary.

### CI/CD Pipeline (CodePipeline + CodeBuild)
- Source: GitHub connection via **CodeStar Connections**.
- Pipeline stages: **Source → Build → Deploy-Staging → Manual Approval → Deploy-Prod**.
- Backend build (CodeBuild):
  1. `pip install -r requirements.txt && pytest` — fail the build on test failure.
  2. Docker build and push to ECR.
  3. Update ECS service (rolling deployment, `minimumHealthyPercent: 100`, `maximumPercent: 200`).
- Frontend build (CodeBuild):
  1. `npm ci && npm run lint && npm run build` — fail on lint or type errors.
  2. `aws s3 sync dist/ s3://<bucket> --delete`
  3. CloudFront cache invalidation on `/*`.
- Separate CodeBuild projects for backend and frontend — they deploy independently.

### Networking
- **VPC** with public and private subnets across 2+ AZs.
- ALB in public subnets, ECS tasks in private subnets.
- **NAT Gateway** for outbound internet from private subnets.
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
- Enable **CDK Nag** (`cdk-nag`) in the pipeline to enforce AWS best practices and catch security issues before deployment.
