# Acme Storefront — Project Instructions

PROJECT-LEVEL CLAUDE.md. Lives at the repo root, committed to version control, so
every teammate gets it on clone or pull. This is the file the exam's "new team
member isn't getting the instructions" question is about: if guidance is only in
`~/.claude/CLAUDE.md`, it is user-scoped and never reaches anyone else.

Always-loaded universal standards belong here. Anything conditional belongs in
`.claude/rules/`; anything on-demand belongs in `.claude/skills/`.

## Stack
Python 3.12 backend, React 19 + TypeScript frontend, Postgres 16, Terraform on AWS.

## Universal standards
- Every behavioural change ships with a test. No exceptions for "trivial" changes.
- Never commit secrets. Config comes from environment variables, never literals.
- Public functions carry type hints and a one-line docstring; private helpers need
  neither unless the logic is non-obvious.
- Currency is stored and computed in integer minor units. Never float dollars.

## Modular imports
Kept short deliberately. A monolithic CLAUDE.md is loaded in full on every single
request, so its size is a tax on every interaction — which is why the detail lives
in imported files and path-scoped rules instead.

@standards/python.md
@standards/testing-standards.md

## What is NOT in this file
- Test conventions        -> .claude/rules/testing.md          (loads for **/*.test.*)
- API handler conventions -> .claude/rules/api-conventions.md  (loads for src/api/**)
- Terraform conventions   -> .claude/rules/terraform.md        (loads for terraform/**)
- Codebase mapping        -> .claude/skills/codebase-map/      (on demand, forked)
