# Coding Instructions

## General

- All configuration must be production-ready standard — no placeholder values, TODO stubs, or "good enough for now" defaults. Every config entry should be deployable to production as-is.

## Branching

**No commit is ever made on `main`.** Not a fixup, not a one-line doc change, not "this is too small for a PR". `main` advances only by merging a pull request; a commit authored on `main` is a mistake to be moved onto a branch, not a shortcut to be kept.

Two reasons this is absolute rather than a preference: `main` is the deployment branch — `.github/workflows/deploy.yml` triggers on push to it — so a commit landing there aims a deploy at whatever was in the working tree at the time; and this repository has other people working in it, so `main` is shared state and a direct commit is a change nobody reviewed.

**One branch per task**, cut from an up-to-date `main` before the first edit, named for the task's stable ID so the branch, the issue and the eventual PR line up:

```bash
git fetch origin && git switch -c feat/inf-08-thumbnails origin/main
```

Use the prefix that matches the work — `feat/`, `fix/`, `docs/`, `chore/` — followed by the lowercased task ID and a short slug.

If a commit does end up on `main` before it is pushed, move it rather than push it:

```bash
git branch feat/inf-08-thumbnails      # keep the commit, on a branch
git branch -f main origin/main         # main back to the remote (run from another branch)
```

## Worktrees for parallel work

**One worktree per task whenever subagents are involved.** Agents working in parallel share a single checkout unless told otherwise, and two of them editing the same tree — or one switching branches under another — corrupts both. Give each task its own worktree so the branch it is on is its own:

```bash
git worktree add ../qbiq_h-inf-08 -b feat/inf-08-thumbnails origin/main
git worktree list                       # what exists now
git worktree remove ../qbiq_h-inf-08    # once the branch has landed
```

With the `Agent` tool, `isolation: "worktree"` does this per agent and cleans up a worktree left unchanged. A single agent working one task in sequence does not need one — the isolation is worth its cost only when work actually runs concurrently.

## Python / FastAPI

### Project Structure
```
backend/
  app/
    __init__.py
    main.py             # FastAPI app, route definitions
    models.py           # Pydantic request/response schemas
    settings.py         # Environment-driven configuration
    <domain>.py         # Business logic classes
    repositories/       # Storage implementations behind Protocols
  tests/
    __init__.py
    test_<module>.py    # Mirror app/ structure
  requirements.txt
```
The backend lives in `backend/` and the SPA in `frontend/`, so each Docker build context covers one service only.

### Code Style
- Type-annotate all function signatures including return types.
- Use `dataclass(frozen=True)` for internal value objects that don't need Pydantic validation.
- Use Pydantic `BaseModel` for API request/response schemas.
- Route handlers must be thin — delegate to business logic classes.
- Use `snake_case` for functions and variables, `PascalCase` for classes.
- One class/concern per file.

### Dataclasses

Domain types are frozen dataclasses (`app/domain/`). They are the source of truth for what a
concept *has*, so **derive conversions from them rather than restating their fields**. A hand-written
field list is a second definition that drifts silently: adding a field to the dataclass leaves the
converter quietly dropping it, and no test fails, because the test was written against the same
incomplete list.

- **Serializing** — `dataclasses.asdict()` walks nested dataclasses, tuples, and lists already. Use
  it instead of building the dict field by field.
- **Deserializing** — take the field names from `dataclasses.fields(T)`, not from a literal list.
  Reconstruct nested types explicitly, since `asdict` flattens them to plain dicts:
  ```python
  _FIELDS = tuple(f.name for f in fields(Product))

  def _to_product(data: dict[str, Any]) -> Product:
      known = {name: data[name] for name in _FIELDS}
      known["category"] = Category(**data["category"])
      return Product(**known)
  ```
- **Domain → Pydantic** — set `from_attributes=True` on the schema and call `Model.model_validate(obj)`.
  Pydantic reads the dataclass's attributes directly, recursively, when the nested schemas share the
  base. Do not write a `from_domain` that names every field; put one generic `from_domain` on the
  shared base class instead. Extra attributes are ignored, so passing a `ProductDetail` where a
  summary schema is expected projects it down rather than failing.
- **When to write the mapping by hand:** when it is a genuine *reshape* rather than a copy — the
  field names differ, values are computed, or one type flattens another. `app/api/cart.py`'s
  `_to_cart_view` flattens `LineItem{product, quantity}` into a flat wire row and derives the
  currency; that is logic, and it belongs in code, not in a generic converter.
- Never rely on `hash()` or `repr()` of a dataclass for anything persistent (a cache key, an id).
  Both depend on field declaration order and formatting, neither of which is a contract. Build an
  explicit, fixed-order tuple of values and hash that — see
  `app/repositories/cached_product_repository.py::_stable_hash`.

### Configuration
- Use environment variables for all runtime configuration (DB URLs, file paths, feature flags).
- Provide sensible defaults so local development works without any env vars set.
- Load configuration at module level so it's available at startup.

### Testing
- Use `pytest` as the test runner.
- Use FastAPI's `TestClient` for API/integration tests.
- Unit tests should construct dependencies inline (no shared global fixtures for business logic).
- Test both success paths and error/edge cases.
- Run tests from `backend/`: `pytest -q`
- Run a single test: `pytest tests/test_file.py::test_name`

### Dependencies
- Pin minimum versions in `requirements.txt` (e.g., `fastapi>=0.115.0`).
- For production, generate a locked `requirements.lock` with exact versions.

---

## Vue / TypeScript

### Project Structure
```
frontend/
  package.json
  vite.config.ts
  src/
    main.ts             # Entry point (createApp)
    App.vue             # Root component
    types.ts            # Shared type definitions
    api/client.ts       # The only module that calls fetch
    router/index.ts     # Route definitions
    components/
      <Name>.vue        # One component per file, PascalCase filename
    composables/
      use<Name>.ts      # Reusable stateful logic, camelCase `use` prefix
    stores/
      <name>.ts         # Pinia stores
```

### Code Style
- Single-File Components with `<script setup lang="ts">` only — no Options API, no `defineComponent` wrappers.
- Declare props with type-only `defineProps<Props>()` against a standalone `interface Props` above the template usage; declare events with type-only `defineEmits<{ ... }>()`.
- Use `withDefaults()` (or default values in the destructured props) for optional props — no runtime prop objects.
- One component per `.vue` file; the filename is the component name (`PascalCase.vue`).
- `camelCase` for functions/variables, `PascalCase` for components/types/interfaces.
- Keep parsing and transformation logic in pure functions outside components (`parser.ts`, not inside SFCs).
- Shared types go in `types.ts`, not scattered across components.
- Extract reusable stateful logic into composables (`use*.ts`) rather than mixins.

### State & Reactivity
- Use `ref()` for primitives and `reactive()` sparingly for object state; prefer `ref` for consistency.
- Use `computed()` to derive state from props instead of duplicating props into local refs.
- Use `watch` / `watchEffect` for side effects; return or register cleanup via the `onCleanup` callback.
- Use `onMounted` / `onUnmounted` for lifecycle work, and always tear down subscriptions, timers, and listeners in `onUnmounted`.
- Never mutate props — emit an event or use `defineModel()` for two-way binding.
- Reach for Pinia only when state is genuinely shared across unrelated components; local state and props stay local.

### Templates
- Always pair `v-for` with a stable `:key`; never put `v-if` and `v-for` on the same element.
- Prefer `<template v-if>` blocks over deeply nested conditional markup.

### Layout
- Use CSS Grid or Flexbox in `<style scoped>` blocks unless a CSS framework is adopted.
- Component styles must be `scoped`; global styles live in a single top-level stylesheet.

### Build & Lint
- `npm run dev` — Vite dev server with HMR.
- `npm run build` — Type-check (`vue-tsc -b`) then Vite production build.
- `npm run lint` — ESLint (`eslint-plugin-vue`, `vue3-recommended` ruleset).
