---
description: Run the team's standard code review checklist over the current diff
argument-hint: [base-branch]
allowed-tools: Bash(git diff:*), Bash(git log:*), Read, Grep, Glob
---

# /review

PROJECT-SCOPED SLASH COMMAND — this is exam Sample Question 4.

Because it lives in `.claude/commands/` inside the repository, it is
version-controlled and automatically available to every developer on clone or pull.
`~/.claude/commands/` would make it personal and unshared; CLAUDE.md is for project
instructions, not command definitions; and `.claude/config.json` with a commands
array does not exist.

Review the diff against $1 (default: `main`).

Report ONLY:
- Bugs: logic errors, boundary conditions, unhandled exceptions, race conditions
- Security: injection, authz gaps, secret handling, unsafe deserialisation
- Money: any float arithmetic on currency, any rounding that is not banker's rounding

Explicitly SKIP:
- Formatting, naming preferences, import ordering
- Patterns that are locally consistent with the surrounding file
- Missing tests (a separate command covers that)

For each finding output exactly:
`SEVERITY | file:line | what breaks | suggested fix`

Severity is one of BLOCKER / MAJOR / MINOR, defined as:
- BLOCKER: incorrect behaviour reaches production or data is lost
- MAJOR:   incorrect behaviour under a reachable edge case
- MINOR:   works, but will confuse the next reader in a way that risks a future bug
