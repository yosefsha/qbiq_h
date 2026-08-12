"""HTTP route modules, each wrapping one FastAPI `APIRouter`.

Kept apart from `app.main` so that `app.main`'s only job stays wiring
(middleware order, CORS, and `app.include_router(...)`) — see the module
docstring there.
"""
