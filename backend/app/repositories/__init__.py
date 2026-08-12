"""Storage-backed implementations of the domain repository Protocols.

Each module here implements one Protocol from `app.domain.repositories`
against one storage engine, and is the only place a SQLAlchemy or Redis type
is allowed to meet a domain type. Callers depend on the Protocol, never on a
module in this package — that is what lets tests substitute
`app.domain.fakes.InMemoryRepository` without a live Postgres or Redis.
"""
