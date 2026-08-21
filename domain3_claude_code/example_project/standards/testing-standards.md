# Testing Standards

Imported with `@standards/testing-standards.md`. Documented here so that
CI-invoked test generation produces useful tests rather than volume (Task 3.6).

## What makes a test valuable here
- It fails when the behaviour regresses, and only then.
- It pins a boundary, an error path, or a money calculation.
- It does NOT assert that a mock was called, or restate the implementation.

## Available fixtures — use these, do not rebuild them
- `db`             transactional Postgres session, rolled back per test
- `frozen_clock`   pins `utcnow()`; required for anything date-dependent
- `fake_gateway`   payment gateway stub with `.fail_next()` and `.timeout_next()`
- `order_factory`  builds an Order with sensible defaults; override per test

## Do not generate
- Tests for generated code, migrations, or `__init__.py`
- Getter/setter tests
- Duplicates of scenarios already in the suite — the existing test files are
  provided in context precisely so you can avoid this
