"""Canonical dependency keys shared by every router.

`get_product_repository` lives here, on its own, for one reason: the
catalogue router (BE-05) and the Cart router (BE-07) must resolve a product
id through the *same* repository. When each router owned its own provider,
they disagreed about what a product id even was — the catalogue served the
database primary key (`"8"`) while the Cart resolved a slug of the product
name (`"codesight-static-analyzer-team-licence"`), so a `productId` taken
straight from a listing 404'd on `POST /api/cart/items`. One key makes that
class of drift impossible rather than merely unlikely.

Deliberately free of any SQLAlchemy import, so the route modules that depend
on this stay free of one too (an explicit Done-when on BE-05). The concrete,
storage-bound provider lives in `app.api.deps`, and `app.main` is the single
place the two are joined.
"""

from __future__ import annotations

from app.domain.repositories import ProductRepository


def get_product_repository() -> ProductRepository:
    """Placeholder dependency, always overridden before it can be called.

    `app.main` overrides this key with `app.api.deps.get_sql_product_repository`
    at import time; tests override it with an `app.domain.fakes.InMemoryRepository`.
    Reaching this body means neither happened, which is a wiring bug rather
    than a condition to degrade gracefully from — so it raises loudly instead
    of quietly serving an empty catalogue.
    """
    raise NotImplementedError(
        "get_product_repository must be overridden via app.dependency_overrides"
    )
