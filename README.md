# CCAR-F Lab — Claude Certified Architect, Foundations

Runnable code for every task statement in the *Claude Certified Architect –
Foundations* exam guide (exam code CCAR-F, v1.0, July 2026).

Every module makes **real API calls** and prints what actually happened. Most run
an anti-pattern and the correct pattern back to back against the same input, so
you see the difference rather than reading an assertion about it.

Where a live run does not reproduce the failure the exam describes, the module
says so instead of pretending. That is deliberate — several of these failures are
*intermittent*, and knowing which ones is itself exam-relevant.

---

## Setup

```bash
cd ccar-f-lab
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env        # then put your key in it
.venv/bin/python check_setup.py
```

### Two credential paths — this matters

| Path | Needed by | Credential |
|---|---|---|
| Raw Claude API (`anthropic`) | Domains 2, 4, 5 | `ANTHROPIC_API_KEY` in `.env` |
| Claude Agent SDK (`claude_agent_sdk`) | Domains 1, 3 | Your existing Claude Code login |

Domains 1 and 3 run with no API key at all — they drive the bundled `claude` CLI
using the login already on this machine. If you only have one of the two, run
`check_setup.py` and it will tell you which half of the lab is available.

Put the key in `.env` rather than exporting it. An `export` in one terminal does
not reach a script launched from another, which is a reliable way to lose twenty
minutes to a phantom auth bug. `common.py` loads `.env` automatically and `.env`
is git-ignored.

### Model

Defaults to `claude-opus-5`. Override for cheaper iteration:

```bash
CCAR_MODEL=claude-haiku-4-5 .venv/bin/python domain4_prompting/t4_2_few_shot.py
```

A smaller model actually makes several exercises *clearer* — the gap between the
bad prompt and the good prompt widens.

---

## Coverage map

Every task statement in the blueprint, and where it is exercised.

### Domain 1 — Agentic Architecture & Orchestration (27%)

| Task | Module | Runs on |
|---|---|---|
| 1.1 Agentic loops, `stop_reason` | `domain1_agentic/t1_1_agentic_loop.py` | API key |
| 1.2 Coordinator–subagent orchestration | `domain1_agentic/t1_2_coordinator_subagents.py` | Agent SDK |
| 1.3 Subagent invocation & context passing | `t1_2_...` + `domain1_agentic/t1_3_context_passing.py` | Agent SDK |
| 1.4 Enforcement & handoff patterns | `domain1_agentic/t1_4_enforcement_and_handoff.py` | API key |
| 1.5 Hooks: interception & normalization | `domain1_agentic/t1_5_hooks.py` | Agent SDK |
| 1.6 Task decomposition strategies | `domain1_agentic/t1_6_task_decomposition.py` | API key |
| 1.7 Sessions: resume, fork, staleness | `domain1_agentic/t1_7_sessions.py` | Agent SDK |

### Domain 2 — Tool Design & MCP Integration (18%)

| Task | Module | Runs on |
|---|---|---|
| 2.1 Tool interface design | `domain2_tools_mcp/t2_1_tool_descriptions.py` | API key |
| 2.2 Structured error responses | `domain2_tools_mcp/t2_2_structured_errors.py` | API key |
| 2.3 Tool distribution & `tool_choice` | `domain2_tools_mcp/t2_3_tool_distribution.py` | API key |
| 2.4 MCP integration & scoping | `domain2_tools_mcp/t2_4_mcp_integration.py` + `mcp_server/` + `.mcp.json` | Agent SDK |
| 2.5 Built-in tool selection | `domain2_tools_mcp/t2_5_builtin_tools.py` | Agent SDK |

### Domain 3 — Claude Code Configuration & Workflows (20%)

| Task | Module | Runs on |
|---|---|---|
| 3.1 CLAUDE.md hierarchy & `@import` | `domain3_claude_code/t3_config_hierarchy.py` | Agent SDK |
| 3.2 Slash commands & skills | same | Agent SDK |
| 3.3 Path-scoped rules | same | Agent SDK |
| 3.4 Plan mode vs direct execution | `domain3_claude_code/t3_4_plan_vs_direct.py` | Agent SDK |
| 3.5 Iterative refinement | same | Agent SDK |
| 3.6 CI/CD integration | `domain3_claude_code/t3_6_ci_pipeline.py` | Agent SDK |

**`domain3_claude_code/example_project/` is the study material for this domain.**
It is a complete, working configuration — read the files:

```
example_project/
  CLAUDE.md                          project level, with @imports
  standards/                         imported standards files
  src/api/CLAUDE.md                  directory level
  .claude/rules/testing.md           paths: ["**/*.test.tsx", "**/test_*.py", ...]
  .claude/rules/api-conventions.md   paths: ["src/api/**/*.py"]
  .claude/rules/terraform.md         paths: ["terraform/**/*"]
  .claude/commands/review.md         project-scoped slash command
  .claude/skills/codebase-map/       context: fork, allowed-tools, argument-hint
  .claude/skills/brainstorm-alternatives/
```

### Domain 4 — Prompt Engineering & Structured Output (20%)

| Task | Module | Runs on |
|---|---|---|
| 4.1 Explicit criteria & false positives | `domain4_prompting/t4_1_explicit_criteria.py` | API key |
| 4.2 Few-shot prompting | `domain4_prompting/t4_2_few_shot.py` | API key |
| 4.3 Structured output & schemas | `domain4_prompting/t4_3_structured_output.py` | API key |
| 4.4 Validation & retry loops | `domain4_prompting/t4_4_validation_retry.py` | API key |
| 4.5 Batch processing | `domain4_prompting/t4_5_batch_processing.py` | API key |
| 4.6 Multi-pass & multi-instance review | `domain4_prompting/t4_6_multipass_review.py` | API key |

### Domain 5 — Context Management & Reliability (15%)

| Task | Module | Runs on |
|---|---|---|
| 5.1 Conversation context management | `domain5_context/t5_1_context_management.py` | API key |
| 5.2 Escalation & ambiguity | `domain5_context/t5_2_escalation.py` | API key |
| 5.3 Error propagation across agents | `domain5_context/t5_3_error_propagation.py` | API key |
| 5.4 Large codebase context | `domain5_context/t5_4_codebase_context.py` | Agent SDK |
| 5.5 Human review & confidence | `domain5_context/t5_5_human_review.py` | partly offline |
| 5.6 Provenance & uncertainty | `domain5_context/t5_6_provenance.py` | API key |

`t5_5_human_review.py --offline` runs the whole statistics section with no
credentials at all.

---

## The 12 sample questions in the exam guide

Each is reproduced and *measured* somewhere in the lab:

| Sample Q | Topic | Module |
|---|---|---|
| 1 | Programmatic vs prompt enforcement | `t1_4_enforcement_and_handoff.py` |
| 2 | Tool descriptions drive selection | `t2_1_tool_descriptions.py` |
| 3 | Escalation calibration | `t5_2_escalation.py` |
| 4 | Project-scoped slash commands | `t3_config_hierarchy.py` |
| 5 | Plan mode for architectural work | `t3_4_plan_vs_direct.py` |
| 6 | Path rules vs directory CLAUDE.md | `t3_config_hierarchy.py` |
| 7 | Coordinator decomposition breadth | `t1_2_coordinator_subagents.py` |
| 8 | Structured error propagation | `t5_3_error_propagation.py` |
| 9 | Scoped cross-role tools | `t2_3_tool_distribution.py` |
| 10 | `-p` for non-interactive CI | `t3_6_ci_pipeline.py` |
| 11 | Batch vs synchronous API | `t4_5_batch_processing.py` |
| 12 | Multi-pass review architecture | `t1_6_task_decomposition.py` |

---

## Study aids

- **`ANTIPATTERNS.md`** — every wrong/right pair, with a "why the wrong one is
  tempting" column. That column is the important one: most exam mistakes are
  picking something that is good practice generally but not the answer to the
  question asked.
- **`PRACTICE_QUESTIONS.md`** — 30 new questions in exam format, weighted to the
  blueprint, with rationales for every distractor.

---

## Suggested sequence

Roughly 8–10 hours including reading the output carefully.

1. **Read `ANTIPATTERNS.md` end to end** (45 min). Do not memorise it yet — you
   want to recognise the shapes when you meet them running.
2. **Domain 1** (2.5 h). Highest weight and the conceptual foundation for
   Domain 5. Run `t1_1` → `t1_4` → `t1_5` in that order; the enforcement and hook
   modules only fully land once the loop is concrete.
3. **Domain 3** (1.5 h). Read `example_project/` before running the module — the
   files carry more than the script output does.
4. **Domain 4** (2 h). Run `t4_3` before `t4_4`; the nullability demo sets up the
   retry-limits demo.
5. **Domain 2** (1.5 h). `t2_1` and `t2_2` are the load-bearing ones.
6. **Domain 5** (1.5 h). `t5_5 --offline` first — its statistics are the clearest
   single argument in the lab.
7. **`PRACTICE_QUESTIONS.md` cold**, then re-run the modules for whatever you missed.
8. **Re-read `ANTIPATTERNS.md`** the day before. It should now read as obvious.

---

## Verification status

All 27 modules have been run live. Recorded honestly, because it matters for how
you read their output:

**Demos that clearly differentiate** (the anti-pattern visibly fails, the correct
pattern visibly works):

| Module | Result |
|---|---|
| `t1_1` agentic loop | correct loop ran 3 iterations to `end_turn`; text-presence loop stopped at iteration 1 on `stop_reason='tool_use'` |
| `t1_2` coordinator | 6 parallel spawns in one response, scope partitioned across all creative subdomains |
| `t1_3` context passing | ungrounded prose without context; full attribution + both conflicting figures with it |
| `t1_5` hooks | raw epoch/status_code reached the model without the hook, never with it; over-limit refund blocked pre-execution |
| `t1_7` sessions | resume carried context, fork produced 3 distinct sessions, blind resume answered from a stale cache |
| `t2_2` structured errors | uniform errors → 4 identical decisions; structured → retry / escalate / ask_customer, and empty-result vs access-failure split correctly |
| `t2_4` MCP resources | schema resource yielded the exact status enum absent from every sample record |
| `t3_config` | project CLAUDE.md loaded live; path globs resolved correctly across scattered files |
| `t3_4` plan mode | direct execution modified the file; plan mode attempted a write and changed 0 source files |
| `t3_6` CI | `--json-schema` returned 8 typed findings incl. the CLAUDE.md-derived float-currency rule |
| `t4_1` explicit criteria | noise categories 2 → 1 with recall held at 3/3 |
| `t4_3` structured output | required fields fabricated a PO number; nullable returned null; `conflict_detected` caught the 1635-vs-1735 mismatch |
| `t4_4` validation retry | 3 retries produced `<UNKNOWN>` for genuinely absent info; nullable path returned `None` first try |
| `t5_1` context mgmt | 0/6 facts recovered from summary alone, 6/6 with a case-facts block; 85% token saving on trimmed tool output |
| `t5_2` escalation | 3/7 → 7/7 under explicit criteria; asked for an identifier instead of guessing between matches |
| `t5_3` error propagation | 3/5 → 5/5 coordinator recovery behaviours |
| `t5_5` human review | simple random sampling drew **zero** handwritten docs; stratified measured 25% error in the high-confidence slice |

**Demos that did NOT differentiate on `claude-opus-5`** — the module says so at
runtime rather than implying otherwise:

| Module | What happened |
|---|---|
| `t1_4` enforcement | 0/5 prompt-only violations. The argument is about the *guarantee*, not the observed rate — run `--trials 10`. |
| `t1_6` decomposition | 14/14 both architectures. The fixture sits below the dilution threshold; the exam's diagnosis still holds. |
| `t2_1` tool descriptions | 5/5 routing both ways. Modern models separate these two tools even from thin descriptions. |
| `t2_3` tool distribution | the 18-tool agent stayed in role rather than reaching for web search. |
| `t4_6` multi-instance review | all three architectures found the planted race. |
| `t5_6` provenance | naive synthesis already preserved both conflicting figures with dates. |

This is worth internalising before the exam: **several of these anti-patterns no
longer reproduce reliably on a frontier model at small scale.** The exam's
premises come from production systems — bigger inputs, longer sessions, real
ambiguity. Do not let a clean lab run talk you out of the exam's answer; the
mechanism is what is being tested, not the effect size on eight files.

---

## What this lab does not cover

The exam guide's own out-of-scope list: fine-tuning, API auth/billing, MCP server
deployment and infrastructure, Claude's internal architecture, Constitutional AI
and RLHF, embeddings and vector databases, computer use, vision, streaming/SSE,
rate limits and pricing arithmetic, OAuth and key rotation, cloud provider
configuration, benchmarking, prompt caching internals, and tokenization.

If a practice question you write is about any of the above, it is not on this exam.

---

## A note on API surface drift

The exam is written against a snapshot of the API, and a few things have moved on.
Where that happens, the modules teach **both**: the exam's expected answer, and
what you would actually write today. The clearest case is structured output —
`t4_3_structured_output.py` covers `tool_use` + JSON schema (the exam's answer)
and also `output_config.format` / `client.messages.parse()` (the current API).

On the exam, answer from the exam guide.
