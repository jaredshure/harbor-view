# CLAUDE.md

Guidance for Claude (or any AI coding assistant) working in this
repository.

## What this project is

Harbor View is a piece of **nautical art**, not a tracking dashboard. It
shows commercial vessels visible from one specific waterfront location.
Every implementation decision should be weighed against that intent:
calm, ambient, and minimal — never busy, alarm-driven, or
feature-maximizing.

When in doubt, prefer the design that would look good hanging quietly on
a wall over the one that packs in the most information.

## Before writing code

1. Read `PRODUCT_SPEC.md` in full. It defines scope, tone, and what is
   explicitly out of scope.
2. Read `TASKS.md` and find the current task. **Do not implement ahead
   of the task list.** If Task 003 depends on Task 002 and Task 002
   isn't done, don't skip ahead, even if it seems efficient.
3. If a request conflicts with the product spec's stated non-goals, flag
   the conflict instead of silently implementing it.

## Project conventions

- **Layout**: `src/` layout with the package at `src/harbor_view/`.
  Tests live in `tests/`, mirroring the package structure.
- **Python version**: target the version pinned in `pyproject.toml`.
  Don't introduce syntax newer than that without checking first.
- **Dependencies**: this is meant to stay a small, dependency-light
  project. Justify any new third-party dependency in the PR description
  or commit message — what it buys us, and why a smaller approach
  wasn't sufficient.
- **No speculative abstraction**: don't build plugin systems, config
  frameworks, or multi-backend abstractions for a single-purpose art
  piece unless a task explicitly calls for it. (Sprint 3 did call for
  one: `src/harbor_view/providers/` separates vessel data sourcing
  from rendering via an abstract `VesselProvider` — see
  `docs/sprint-003-notes.md`. Follow that pattern if a future task
  needs another swappable data source; don't invent a second,
  differently-shaped abstraction alongside it.)
- **Output directory**: `output/` is for generated artifacts (rendered
  frames, exported images, etc.). Nothing in it should be hand-edited or
  treated as source.
- **Assets**: `assets/` holds static, checked-in resources (fonts,
  reference images, icons). Don't put generated files here.

## Style

- Follow `PEP 8`; prefer clarity over cleverness.
- Type hints on public functions and class interfaces.
- Docstrings on public modules, classes, and functions — short and
  factual, not aspirational.
- Keep functions small enough to read in one screen.

## Testing

- New behavior gets a test. This includes data-parsing logic, rendering
  logic, and anything touching external data sources (which should be
  mocked in tests — never hit live AIS/vessel-tracking services in the
  test suite).
- Tests live under `tests/`, named `test_*.py`, mirroring the module
  they cover.

## Things to actively avoid

- Don't add tracking features beyond the single fixed vantage point
  (no search-any-ship, no fleet history, no global map).
- Don't add notification/alerting systems — this is meant to be looked
  at, not to interrupt.
- Don't scope-creep into a general AIS library. If general-purpose AIS
  parsing is genuinely useful, it should be a clearly separated,
  optional module — not the spine of the project.
- Don't commit secrets, API keys, or credentials. Use environment
  variables and document them in `docs/`.

## Workflow expectations

- Work through `TASKS.md` in order. Mark tasks as completed where the
  task list provides a place to do so.
- If a task is ambiguous, make the most reasonable assumption consistent
  with `PRODUCT_SPEC.md`, note the assumption in the relevant doc or
  commit message, and proceed — don't stall waiting for clarification
  on small things.
- If a task seems to require something genuinely missing from the spec
  (a hard product decision, not an implementation detail), say so rather
  than guessing.
