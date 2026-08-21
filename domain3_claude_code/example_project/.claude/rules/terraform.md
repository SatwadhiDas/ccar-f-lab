---
paths: ["terraform/**/*"]
---

# Terraform Conventions

Loads only when editing Terraform. This is the exam's literal example of glob
frontmatter (`paths: ["terraform/**/*"]`).

- Never inline a value that differs per environment — use a variable with a
  description and an explicit type.
- Every resource carries the standard tag set: `owner`, `service`, `env`, `cost_center`.
- State is remote. Never commit `.tfstate` or `.terraform/`.
- `prevent_destroy = true` on anything holding data.
- Plan output goes in the PR description before any apply.
