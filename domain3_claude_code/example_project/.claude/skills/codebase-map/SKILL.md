---
name: codebase-map
description: Map an unfamiliar area of the codebase and report a structured summary of its modules, entry points, and data flow. Use when starting work in a part of the repo you have not touched before.
context: fork
allowed-tools: Read, Grep, Glob
argument-hint: [directory or module name]
---

# Codebase Map

Demonstrates all three frontmatter options the exam names.

`context: fork`
    Runs in an ISOLATED sub-agent context. Mapping a module means dozens of Reads
    and Greps whose raw output is enormous and, once summarised, worthless. Forking
    keeps every one of those tool results out of the main conversation and returns
    only the summary. Without it, the exploration output crowds out the actual work
    you were about to do. This is the same instinct as the Explore subagent in
    Task 3.4 and the delegation pattern in Task 5.4.

`allowed-tools: Read, Grep, Glob`
    Restricts tool access for the duration of the skill. Read-only by construction —
    a mapping skill has no business writing files, so it cannot. The exam's framing
    is limiting tool access to prevent destructive actions.

`argument-hint: [directory or module name]`
    Prompts the developer for the parameter when they invoke `/codebase-map` with no
    argument, instead of the skill guessing or failing.

## Procedure

Map $1.

1. Glob the directory tree to establish shape before reading anything.
2. Grep for entry points: route registrations, CLI handlers, exported symbols.
3. Read ONLY the files the entry points reach. Follow imports outward; stop when
   you leave the target module.
4. Return a structured summary:
   - Entry points, one line each
   - Core modules and each one's single responsibility
   - Data flow from entry point to persistence
   - External dependencies crossed (network, DB, queue)
   - Anything surprising: dead code, duplicated logic, a leaking abstraction

Return the summary only. Do not paste file contents — that defeats the fork.
