---
paths: ["**/*.test.ts", "**/*.test.tsx", "**/test_*.py", "**/*_test.py"]
---

# Test File Conventions

PATH-SCOPED RULE. The YAML frontmatter above is the whole point: this file loads
ONLY when a matching file is being edited, so its tokens are not spent on the other
90% of requests.

This is exam Sample Question 6. Test files live next to the code they test
(`Button.test.tsx` beside `Button.tsx`), so they are spread across every directory
in the repo. A directory-level CLAUDE.md cannot express "all test files anywhere";
a glob can. That is why the answer is `.claude/rules/` with glob frontmatter rather
than subdirectory CLAUDE.md files.

- One behaviour per test. The name states the behaviour, not the function name:
  `test_refund_rejected_after_window_expires`, not `test_refund_2`.
- Arrange / act / assert, separated by blank lines.
- Use `frozen_clock` for anything time-dependent. Never `sleep`.
- Never assert on mock call counts. Assert on observable behaviour.
- Cover the boundary, not just the happy path: at the limit, one past it, and the
  empty/null case.
