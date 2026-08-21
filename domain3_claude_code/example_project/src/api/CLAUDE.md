# src/api — Directory-Level Instructions

DIRECTORY-LEVEL CLAUDE.md, the third tier of the hierarchy. Loads when working in
this subtree, in addition to the root CLAUDE.md.

Use this tier when conventions genuinely map to a DIRECTORY. Use `.claude/rules/`
with globs instead when they map to a FILE TYPE that is scattered across
directories — that is the distinction Sample Question 6 turns on.

Note the overlap with `.claude/rules/api-conventions.md`, which is deliberate so you
can compare the two mechanisms side by side. In a real repository you would pick one;
the glob rule is usually the better choice because it survives a directory rename.

## This subtree
- Handlers here are the public HTTP surface. Treat every input as hostile.
- Rate limiting is applied by the gateway, not here. Do not add per-handler limiters.
- Response envelopes are defined in `src/api/envelope.py`. Do not invent new shapes.
