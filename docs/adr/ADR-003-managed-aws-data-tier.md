# Managed AWS data tier: RDS Postgres and ElastiCache for Redis

The catalogue lives in **Amazon RDS for PostgreSQL** and Sessions, Carts, and the product-query cache live in **ElastiCache for Redis**. Both sit in private subnets of the same VPC as the ECS tasks, reachable only from the task security group. The Vue SPA is served from S3 through CloudFront, with an `/api/*` cache behavior routed to the ALB so that browser and API share one origin.

## Why not a JSON mock store

The assignment permits a file-based mock, but it makes two of its own requirements incoherent. "Robust server-side filtering and sorting" and "caching with TTL" are only meaningful when a query costs something, and a JSON file loaded into a Python list at startup costs nothing — caching it in Redis would add a network hop, a serialization format, and an invalidation problem in order to make the application measurably slower. Postgres makes filtering real SQL (`ILIKE`, `ORDER BY` over a whitelisted column set) and makes caching a defensible optimisation rather than theatre.

## Considered Options

- **Memcached as the ElastiCache engine.** Rejected: no replication, no persistence, no failover, and no data structures beyond flat string keys. Losing a node would silently empty every Cart it held.
- **MemoryDB instead of ElastiCache.** A durable, multi-AZ Redis that could hold Carts safely as a primary store. Rejected on cost for now, but it is the correct upgrade if Carts ever hold anything of value.
- **SQLite.** Rejected on dev/prod parity: it disagrees with Postgres on types, constraints, and case-sensitive matching, so the `ILIKE` name filter would behave differently locally than in production — the exact class of bug that only appears after deploy.

## Eviction: `noeviction`, not a `volatile-*` policy

ElastiCache is a cache by default, and a cache is allowed to throw data away. Sessions, Carts, and cached product queries share one keyspace and every one of those keys carries a TTL, so any `volatile-*` policy treats a live Cart and a stale product page as equally disposable. The failure is silent: a shopper's Cart empties itself and nothing in the application ever learns why.

**Decision: one replication group with `maxmemory-policy noeviction`, `reserved-memory-percent 25`, and Carts kept out of Postgres.**

Under `noeviction` a write that would exceed `maxmemory` is refused with an error instead of being made room for. That is the trade: the failure moves from *silent loss of a shopper's Cart* to *a loud, attributable write error on whichever request filled the node*, which surfaces as a 5xx and an alarm rather than as a support ticket. For state, a refused write is always better than a discarded one — a Cart the shopper can retry beats a Cart that quietly emptied.

`reserved-memory-percent 25` keeps a quarter of the node out of the data set so that replication and failover buffers, which are what actually spike under load, cannot be the thing that pushes the node into refusing writes.

Rejected alternatives:

- **Separate cache and state clusters.** Correct in principle, and the right move once the cache is large enough to be the reason memory runs out. Rejected for now on standing cost and operational surface: two replication groups, two failover configurations, two sets of alarms, for a working set whose entire state fraction — one small hash per active Shopper — is a rounding error against the node. Recorded here as the upgrade path, and the trigger for taking it is the memory alarm firing on cache growth rather than on traffic.
- **Separate keyspaces (Redis logical databases, or a key prefix) in one cluster.** Does not solve anything: `maxmemory-policy` is a property of the node, not of a keyspace, so an LRU policy would still evict Carts. The prefix separation is worth keeping for observability, but it is not a control.
- **Moving Carts to Postgres.** Removes the eviction question entirely, but at the cost of a write to the catalogue database on every `POST /cart/items` for state that is deliberately short-lived and never queried across Shoppers — and ADR-001 makes the Cart server-owned precisely so it can live in fast, TTL-managed storage. Reconsider together with MemoryDB if Carts ever need to survive longer than a session.

The local Compose stack already runs `--maxmemory-policy noeviction` for this reason, so laptop and production now fail the same way under memory pressure rather than differently.

## Consequences

- Same-origin routing through CloudFront keeps the session cookie `SameSite=Lax`; a separate API subdomain would force it to `None`.
- Neither S3 nor CloudFront is in the VPC — they are edge services. Only ECS, RDS, and ElastiCache share the network boundary.
- Private subnets need a NAT gateway for outbound pulls, which carries standing cost.
- Everything is provisioned with AWS CDK (Python) from `infra/`, per `CLAUDE.md`: `infra/stacks/data_stack.py` holds the instance, the replication group, their subnet groups, and the two security groups.
- Local development substitutes Postgres and Redis containers for the managed services. Parity rests entirely on connection details coming from environment variables, so no code may reference an AWS-specific endpoint.
- Encryption in transit is on for the replication group, so the deployed client speaks `rediss://` with a Redis AUTH token from Secrets Manager, while the local container speaks plain `redis://`. That is the one connection detail that differs in shape and not just in value between laptop and production.
- `noeviction` makes memory pressure a visible failure rather than an invisible one, which only pays off if someone is watching: the memory alarm on the replication group is what converts a refused write into an action, and it is the trigger for splitting cache and state (see above).
