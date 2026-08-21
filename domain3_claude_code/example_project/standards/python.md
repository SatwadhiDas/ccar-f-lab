# Python Standards

Imported into the root CLAUDE.md with `@standards/python.md`.

The @import mechanism exists so each package can pull in exactly the standards its
maintainers judge relevant, instead of every developer carrying every rule. Splitting
this way also means editing one standard does not force a review of one giant file.

- Format with ruff; line length 100.
- Prefer dataclasses over dicts for anything crossing a module boundary.
- Raise domain exceptions (`RefundWindowExpired`), never bare `Exception`.
- No mutable default arguments.
- Log with `structlog`; never `print` outside of scripts under `tools/`.
