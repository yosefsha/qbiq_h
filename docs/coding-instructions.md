# Coding Instructions

## General

- All configuration must be production-ready standard — no placeholder values, TODO stubs, or "good enough for now" defaults. Every config entry should be deployable to production as-is.

## Python / FastAPI

### Project Structure
```
app/
  __init__.py
  main.py            # FastAPI app, route definitions
  models.py           # Pydantic request/response schemas
  <domain>.py         # Business logic classes
  <domain>_loader.py  # Data loading / parsing utilities
tests/
  __init__.py
  test_<module>.py    # Mirror app/ structure
config/
  *.json              # Runtime configuration files
```

### Code Style
- Type-annotate all function signatures including return types.
- Use `dataclass(frozen=True)` for internal value objects that don't need Pydantic validation.
- Use Pydantic `BaseModel` for API request/response schemas.
- Route handlers must be thin — delegate to business logic classes.
- Use `snake_case` for functions and variables, `PascalCase` for classes.
- One class/concern per file.

### Configuration
- Use environment variables for all runtime configuration (DB URLs, file paths, feature flags).
- Provide sensible defaults so local development works without any env vars set.
- Load configuration at module level so it's available at startup.

### Testing
- Use `pytest` as the test runner.
- Use FastAPI's `TestClient` for API/integration tests.
- Unit tests should construct dependencies inline (no shared global fixtures for business logic).
- Test both success paths and error/edge cases.
- Run a single test: `pytest tests/test_file.py::test_name`

### Dependencies
- Pin minimum versions in `requirements.txt` (e.g., `fastapi>=0.115.0`).
- For production, generate a locked `requirements.lock` with exact versions.

---

## Vue / TypeScript

### Project Structure
```
src/
  main.ts             # Entry point (createApp)
  App.vue             # Root component
  types.ts            # Shared type definitions
  parser.ts           # Pure utility functions
  components/
    <Name>.vue        # One component per file, PascalCase filename
  composables/
    use<Name>.ts      # Reusable stateful logic, camelCase `use` prefix
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
