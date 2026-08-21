---
name: brainstorm-alternatives
description: Generate and compare several implementation approaches for a design decision, then recommend one. Use before committing to an architecture.
context: fork
allowed-tools: Read, Grep, Glob
argument-hint: [the decision to explore]
---

# Brainstorm Alternatives

The second exam-named use of `context: fork`: EXPLORATORY context.

Weighing four approaches means reasoning through three you will discard. Left in
the main conversation, those three rejected branches stay in context for the rest of
the session and keep influencing later answers — the model has "considered and
rejected" material sitting next to the work. Forking returns the comparison and the
recommendation, and drops the discarded reasoning.

## Procedure

Explore $1.

1. Read enough of the codebase to ground the options in what actually exists.
2. Produce 3-4 genuinely distinct approaches. Not one real option and three straw men.
3. For each: how it works, what it costs, what it forecloses, when it is wrong.
4. Recommend one, and state the single condition that would change the recommendation.
