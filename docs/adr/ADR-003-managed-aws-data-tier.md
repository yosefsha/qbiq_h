# Managed AWS data tier: RDS Postgres and ElastiCache for Redis

The catalogue lives in **Amazon RDS for PostgreSQL** and Sessions, Carts, and the product-query cache live in **ElastiCache for Redis**. Both sit in private subnets of the same VPC as the ECS tasks, reachable only from the task security group. The Vue SPA is served from S3 through CloudFront, with an `/api/*` cache behavior routed to the ALB so that browser and API share one origin.

## Why not a JSON mock store

The assignment permits a file-based mock, but it makes two of its own requirements incoherent. "Robust server-side filtering and sorting" and "caching with TTL" are only meaningful when a query costs something, and a JSON file loaded into a Python list at startup costs nothing — caching it in Redis would add a network hop, a serialization format, and an invalidation problem in order to make the application measurably slower. Postgres makes filtering real SQL (`ILIKE`, `ORDER BY` over a whitelisted column set) and makes caching a defensible optimisation rather than theatre.

## Considered Options

- **Memcached as the ElastiCache engine.** Rejected: no replication, no persistence, no failover, and no data structures beyond flat string keys. Losing a node would silently empty every Cart it held.
- **MemoryDB instead of ElastiCache.** A durable, multi-AZ Redis that could hold Carts safely as a primary store. Rejected on cost for now, but it is the correct upgrade if Carts ever hold anything of value.
- **SQLite.** Rejected on dev/prod parity: it disagrees with Postgres on types, constraints, and case-sensitive matching, so the `ILIKE` name filter would behave differently locally than in production — the exact class of bug that only appears after deploy.

## Consequences

- Same-origin routing through CloudFront keeps the session cookie `SameSite=Lax`; a separate API subdomain would force it to `None`.
- Neither S3 nor CloudFront is in the VPC — they are edge services. Only ECS, RDS, and ElastiCache share the network boundary.
- Private subnets need a NAT gateway for outbound pulls, which carries standing cost.
- Everything is provisioned with AWS CDK (Python) from `infra/`, per `CLAUDE.md`. That directory currently has no `cdk.json` and defines no data stack, so both must be added before any of this can synthesize.
- Local development substitutes Postgres and Redis containers for the managed services. Parity rests entirely on connection details coming from environment variables, so no code may reference an AWS-specific endpoint.
- **Open:** ElastiCache is evictable. Every key we store carries a TTL, so under memory pressure a `volatile-*` policy can evict Carts alongside cache entries. Resolve by separating cache and session keyspaces, running `noeviction` with headroom, or moving Carts to Postgres.
