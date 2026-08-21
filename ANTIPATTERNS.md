# Anti-Pattern Reference — CCAR-F

The exam is almost entirely "pick the right option among plausible ones." Every
distractor is a real thing somebody has shipped. This file is the wrong/right
pairs, with the reason each wrong answer is tempting — that last column is what
you actually need under time pressure, because in the moment the distractors will
not look wrong.

Read the "Why it's tempting" column carefully. Most exam mistakes are not
knowledge failures; they are picking an answer that is *good practice in general*
but *not the answer to the question asked*.

---

## Domain 1 — Agentic Architecture & Orchestration (27%)

| ❌ Wrong | ✅ Right | Why the wrong one is tempting |
|---|---|---|
| Terminate the loop by parsing the assistant's text for "done" / "finished" | Terminate on `stop_reason == "end_turn"` | It reads naturally and it works in testing, right up until the model phrases completion differently. |
| Terminate when the response contains a text block | Terminate on `stop_reason` | Almost right. Claude routinely emits text *and* `tool_use` in the same response — you return narration as the final answer and never run the tools. |
| Use an iteration cap as the primary stopping mechanism | Cap as a runaway *backstop*; `stop_reason` decides | Caps are genuinely good practice. The error is making it the control-flow mechanism — a cap cannot tell "finished in 3 turns" from "stuck for 3 turns." |
| Append only the assistant's *text* to history | Append the entire `response.content` | Feels tidier. It orphans the `tool_use` blocks and the next request 400s. |
| Split tool results across several user messages | All `tool_result` blocks for a turn in **one** user message | Looks equivalent. It silently teaches Claude to stop making parallel tool calls. |
| Drop a `tool_use` block whose tool failed | Return `tool_result` with `is_error: true` | "It failed, so there's nothing to send." Every `tool_use` needs a matching result or the request is invalid. |
| Enforce a required tool ORDER with a system prompt ("CRITICAL: you MUST verify first") | A programmatic prerequisite gate in the dispatcher | This is **Sample Q1**. Emphatic prompts feel like enforcement. They have a non-zero failure rate, and no wording drives it to zero. |
| Enforce a refund ceiling in the system prompt | `PreToolUse` hook returning `permissionDecision: "deny"` | Same trap, financial stakes. You cannot show an auditor a system prompt as evidence of a spend limit. |
| Block a policy-violating call with a bare denial | Deny **plus** a reason naming the alternative workflow | Blocking is the hard part, so it feels done. A bare denial strands the agent instead of redirecting it to escalation. |
| Normalise timestamps/status codes by instructing the model | `PostToolUse` hook transforming the result | It usually works. The times it doesn't, you ship a wrong date to a customer. Deterministic transforms belong in code. |
| Fix a routing classifier when tool ORDER is wrong | Fix the ordering; a classifier changes tool *availability* | Sample Q1 distractor D. Availability and ordering are different axes. |
| Coordinator without `"Task"` in `allowed_tools` | `allowed_tools=[..., "Task"]` | It fails silently — the coordinator just does the work itself and you wonder why delegation "isn't helping." |
| Assume subagents inherit the parent's context | Put every needed finding **in the subagent's prompt** | "Summarise the findings above" *looks* like it works. It produces confident, ungrounded prose and never errors. |
| Spawn subagents one per turn | Emit multiple `Task` calls in a **single** response | Sequential code feels natural. Latency becomes the sum instead of the max. |
| Let subagents talk to each other | Route everything through the coordinator (hub-and-spoke) | Direct is "more efficient." You lose observability, consistent error handling, and controlled information flow. |
| Always run the full subagent pipeline | Coordinator dynamically selects which subagents to invoke | Predictable and easy to reason about. A simple query pays for three round trips. |
| Blame the search/analysis/synthesis agent for coverage gaps | Blame the **coordinator's decomposition** | This is **Sample Q7**. The subagents all succeeded — they executed exactly what they were assigned. |
| Prompt a coordinator with STEP 1 / STEP 2 / STEP 3 | Specify goals + quality criteria | Procedural prompts feel controllable. They prevent subagents from adapting. |
| Single-pass review over 14 files | Per-file passes + a separate cross-file integration pass | This is **Sample Q12**. It's one call and it's simpler. |
| Fix attention dilution with a bigger context window | Split the passes | The most seductive distractor on the exam. Capacity ≠ attention quality. |
| Require 2-of-3 consensus to reduce false positives | Report everything, filter in a later pass | Sounds statistically sound. It **suppresses real bugs** — subtle ones are caught intermittently, by definition. |
| Resume a session whose tool results are broadly stale | Start fresh with an injected structured summary | Resuming preserves work. It also drags a stale transcript the agent can't audit. |
| Resume blind after files changed | Resume and **name the files that changed** | The agent *often* re-reads on its own. "Often" is not a control — the failure is intermittent and invisible. |

---

## Domain 2 — Tool Design & MCP Integration (18%)

| ❌ Wrong | ✅ Right | Why the wrong one is tempting |
|---|---|---|
| Fix misrouting with 5–8 few-shot routing examples | Expand the tool **descriptions** | This is **Sample Q2**. Few-shot is a real technique — but here it adds tokens to every request without touching the root cause. |
| Fix misrouting with a keyword routing layer | Fix the descriptions | Deterministic, testable, feels like engineering. It's over-engineered and discards the model's language understanding. |
| Consolidate two confusable tools into one generic tool | Fix descriptions first | A legitimate architecture change — just not the *first step* the question asks for. |
| Two tools with near-identical descriptions (`analyze_content` / `analyze_document`) | Rename + re-scope with explicit BOUNDARY lines | Both descriptions are individually accurate. Neither tells the model when to prefer the other. |
| A generic `analyze_document` | Split into `extract_data_points`, `summarize_content`, `verify_claim_against_source` | Fewer tools seems better for selection. Not when one tool has three unrelated jobs. |
| Blame the tool descriptions when routing is wrong | Also audit the **system prompt** for keyword-sensitive phrasing | You just rewrote the descriptions, so they're top of mind. A stray "always analyze the document" can override them. |
| `"Operation failed. Please try again."` | `isError` + `errorCategory` + `isRetryable` + message | Uniform errors are simple and consistent. They collapse four situations that demand four different recoveries. |
| Let the agent infer retryability from the message | The **server** sets `isRetryable` | It usually infers correctly. Business-rule violations then get retried until the agent gives up. |
| Return a business-rule error with no customer wording | Include a customer-safe explanation | The agent can paraphrase. It will — and it will invent policy while doing so. |
| Return `[]` for a search that failed | Distinguish access failure from valid empty result | Both "return nothing." One should be retried; the other means "you have none." |
| Give every agent all 18 tools | Scope tools per role | Maximum capability, one config. Selection reliability degrades and agents misuse off-role tools. |
| Give the synthesis agent full web search | A scoped `verify_fact` for the 85% simple case | It removes round trips. It also has the synthesis agent doing research — **Sample Q9**. |
| A generic `fetch_url` | A constrained `load_document` that validates | Flexible and reusable. Generic tools become the agent's universal escape hatch. |
| `tool_choice: "auto"` when you need structured output | `tool_choice: "any"` | "Auto" is the default and usually calls the tool. "Usually" breaks your parser eventually. |
| Configure a shared team MCP server in `~/.claude.json` | `.mcp.json` (project-scoped, committed) | It works on your machine. New teammates get nothing — and this is exactly how the exam phrases the symptom. |
| Commit credentials in `.mcp.json` | `${GITHUB_TOKEN}` env-var expansion | Otherwise you can't share the config. Expansion is what makes project scope viable. |
| Write a custom MCP server for Jira | Adopt the community server | You control it. You also maintain it forever, for a solved problem. |
| A thin MCP tool description | A full description (inputs, outputs, when-to-use, boundaries) | The tool works when called. The agent prefers `Grep` because it understands `Grep` — a description-quality *adoption* problem. |
| Expose a DB schema as a `get_schema` tool | Expose it as an MCP **resource** | Tools are the familiar mechanism. Resources give visibility without exploratory round trips. |
| `Grep` to find test files | `Glob` — that's a **path** question | Grepping `def test_` works by accident and misses empty test files. |
| `Bash` + `find`/`grep` | `Glob` / `Grep` tools | Familiar from the terminal. You lose structured results and the permission surface. |
| Give up when `Edit` can't find a unique match | Widen the anchor, or `Read` + `Write` | It feels like a tool limitation. It's a safety property — silently editing one of three identical lines is a coin flip. |
| `Glob **/*.py` then `Read` everything | Grep the entry point → Read → follow imports | Thorough. It exhausts the window before any reasoning happens. |

---

## Domain 3 — Claude Code Configuration & Workflows (20%)

| ❌ Wrong | ✅ Right | Why the wrong one is tempting |
|---|---|---|
| Team instructions in `~/.claude/CLAUDE.md` | Project-level `CLAUDE.md`, committed | It works for you immediately. It never travels with the repo. |
| One monolithic `CLAUDE.md` | Small root + `@import` + `.claude/rules/` | Everything in one place. It's loaded on **every** request — its size is a permanent tax. |
| Per-directory `CLAUDE.md` for test conventions | `.claude/rules/` with `paths: ["**/*.test.tsx"]` | This is **Sample Q6**. Directory files are directory-*bound*; test files are scattered everywhere. |
| One `CLAUDE.md` with a section per area | Path-scoped rules | Organised and readable. It relies on the model *inferring* which section applies. |
| Skills for conventions that must apply automatically | Path-scoped rules | Skills are the newer mechanism. They need invocation, which contradicts "automatically." |
| Slash command in `~/.claude/commands/` for the team | `.claude/commands/` | This is **Sample Q4**. Personal scope is never shared. |
| Define commands in `CLAUDE.md` | `.claude/commands/*.md` | CLAUDE.md is "the config file." It's for instructions, not command definitions. |
| `.claude/config.json` with a `commands` array | `.claude/commands/` | Sounds plausible. **It does not exist** — a pure invention distractor. |
| Verbose exploratory skill without `context: fork` | `context: fork` | Fork is extra config. Without it, discovery output floods the main conversation. |
| Unrestricted tools in a read-only skill | `allowed-tools: Read, Grep, Glob` | Fewer things to configure. A mapping skill has no business writing files. |
| Editing a shared skill for personal taste | Personal variant in `~/.claude/skills/` under a **different name** | It's right there. You change it for everyone. |
| Direct execution for a monolith→microservices split | **Plan mode** | This is **Sample Q5**. Starting feels productive. |
| "Start direct, switch to plan mode if complexity appears" | Plan mode from the start | The most reasonable-sounding distractor. The complexity is **stated in the requirements** — it isn't going to "appear." |
| Direct execution with comprehensive upfront instructions | Plan mode | Sounds rigorous. It presumes you already know the service boundaries you're trying to discover. |
| Plan mode for a one-line validation fix | Direct execution | "Planning is always safer." You spend more on the plan than the fix. |
| Prose spec that keeps getting misread | 2–3 concrete input/output examples | You explained it clearly. "Standard format" means something different to everyone. |
| `claude "prompt"` in CI | `claude -p "prompt"` | This is **Sample Q10**. It's the command you type locally. In CI it hangs until the job times out. |
| `CLAUDE_HEADLESS=true` | `-p` | Sounds like a real env var. It isn't. |
| `--batch` | `-p` | Sounds like a real flag. It isn't. |
| `claude "..." < /dev/null` | `-p` | It genuinely prevents a blocking read — but treats the symptom, not the interactive mode. |
| Parse prose review output with regex | `--output-format json --json-schema` | Works on the first ten runs. Breaks when the model changes a heading. |
| Re-run CI review without prior findings | Include prior findings + "only new or unaddressed" | Each run is stateless and clean. You re-post identical comments on every push until developers mute the bot. |
| Generate tests without the existing suite in context | Provide existing test files | Fewer tokens. You get duplicates of scenarios already covered. |
| Let the generating session review its own code | A separate, independent instance | Continuity seems efficient. It retains the reasoning that produced the code and won't question it. |

---

## Domain 4 — Prompt Engineering & Structured Output (20%)

| ❌ Wrong | ✅ Right | Why the wrong one is tempting |
|---|---|---|
| "Be conservative, only report high-confidence findings" | Explicit REPORT / DO-NOT-REPORT categories | It reads like precision tuning. It makes the reviewer quieter, not more accurate. |
| "Check that comments are accurate" | "Flag a comment only when claimed behaviour contradicts actual behaviour" | Shorter and clearer to a human. The second is *checkable*. |
| Severity as "high / medium / low" | Each level anchored to a concrete code example | Everyone knows what "high" means. Two runs will disagree. |
| Keep a noisy finding category running while you fix it | **Disable** it, fix offline, re-enable | Removing a feature feels like regression. It's spending trust the accurate categories need. |
| Few-shot examples to fix thin tool descriptions | Fix the descriptions | Few-shot is a legitimate technique — just not for a *missing instruction*. (Sample Q2.) |
| 10+ few-shot examples | 2–4 targeted at the ambiguous middle | More examples = more signal. They ride along on every request forever. |
| Few-shot examples of the obvious cases | Examples of the ambiguous ones, **with reasoning** | Easier to write. The model already handles the obvious cases. |
| Prose describing the output format | Show 2 examples **of** the format | You described it precisely. Descriptions get approximated; examples get reproduced. |
| Prompt "return valid JSON" | `tool_use` with a JSON schema | It mostly works. "Mostly" means a parse error in production. |
| Assume a schema guarantees correctness | Schema kills **syntax** errors; add semantic validation | Valid + schema-compliant *feels* correct. Line items that don't sum are both. |
| Mark every extraction field `required` | Nullable for anything that may be absent | Required = complete data. It's pressure to **fabricate** — the schema becomes a fabrication prompt. |
| Closed enum with no escape hatch | Add `"unclear"` and `"other"` + detail | A tight enum seems more rigorous. It forces a wrong choice for anything unanticipated, undetectably. |
| `tool_choice: "auto"` for extraction | `"any"` when the doc type is unknown | It's the default. It permits a conversational reply. |
| Handle format normalisation in the schema | Normalisation rules in the **prompt**, schema for shape | Schemas feel like the place for constraints. Schemas constrain shape, not interpretation. |
| Retry with "that was wrong, try again" | Original doc + failed extraction + **specific** errors | The model knows what it did. Without the specific errors it resamples rather than converges. |
| Retry until the required field appears | Classify first — absent information never converges | Retries fix things. Each one costs money and raises the odds of eventual fabricated success. |
| Aggregate false-positive rate | `detected_pattern` per finding | It's the number leadership asks for. It tells you nothing about *which rule* to fix. |
| Batch the pre-merge check for the 50% saving | Synchronous for blocking work | 50% is a big number. There's **no latency SLA** — a developer is waiting. |
| Batch + poll for a blocking workflow | Match the API to the workload | Polling feels like it solves the wait. It doesn't change the 24h ceiling. |
| Avoid batch over result-ordering concerns | `custom_id` correlates request↔response | Sounds like a real risk. It's a solved problem. |
| Batch + timeout fallback to real-time | Just use the right API per workload | "Best of both." Duplicate spend and two code paths to maintain. |
| Batch an agentic loop | Synchronous — batch has **no multi-turn tool calling** | It's latency-tolerant, so it seems eligible. It's a capability limit, not a latency judgement. |
| Index batch results by position | Key by `custom_id` | Order looks stable in testing. It is not guaranteed. |
| Resubmit the whole failed batch | Resubmit only failed `custom_id`s, with a fix | Simpler code. You pay full price again for everything that succeeded. |
| "Now review your own work carefully" | An independent instance with no generation context | It's one more turn instead of new infrastructure. It cannot remove the contaminating context. |
| Extended thinking to catch self-review bias | An independent instance | Thinking harder helps a lot of things. Not this — the bias is contextual, not effort-related. |

---

## Domain 5 — Context Management & Reliability (15%)

| ❌ Wrong | ✅ Right | Why the wrong one is tempting |
|---|---|---|
| Progressively summarise the whole conversation | Summarise prose; keep a structured **case-facts** block | Summarisation is *the* standard technique. It reliably destroys amounts, dates and commitments. |
| Trust that facts stated early survive summarisation | Re-inject facts verbatim every turn | They were said clearly. They become "the customer was unhappy about a delay." |
| Dump 20 findings in a flat list | Summary **first**, explicit section headers | It's all in context. Items in the middle get dropped. |
| Store full tool output in context | Trim to relevant fields at the boundary | You might need it later. 35 irrelevant fields get re-sent every turn for the rest of the session. |
| Truncate verbose input at the consuming agent | Restructure at the **producing** agent | Consumer-side is where you noticed the problem. Truncating drops an arbitrary slice. |
| Escalate "when a case is too complex" | Explicit triggers: human request / policy gap / no progress | It sounds like exactly the right rule. "Complex" is undefined, so the model substitutes its own sense of difficulty. |
| Route to a human when self-reported confidence is low | Explicit criteria + few-shot | This is **Sample Q3** distractor B. Confidence gating is a real pattern — but the agent is *already confidently wrong* on hard cases. |
| Train a classifier to predict escalation | Fix the prompt first | It's the "serious engineering" answer. Over-engineered before prompt optimisation was tried. |
| Escalate on negative sentiment | Escalate on policy gaps | Angry customers *do* need care. Sentiment measures upset; complexity is a different variable. |
| Investigate first, then escalate, when a human is requested | Escalate **immediately** | Being helpful first seems better. They asked for a person. |
| Escalate immediately on frustration | Acknowledge, offer resolution, escalate only if reiterated | Symmetrical with the rule above, and wrong — frustration isn't a request. |
| Pick the best-matching customer from several matches | Ask for an additional identifier | "Most recent order" is a reasonable heuristic. It refunds a stranger's order. |
| Subagent returns `"search unavailable"` after retrying | Structured error: type, attempted, partial results, alternatives | This is **Sample Q8** distractor B — and the *retry half is correct*. Collapsing the context afterwards is what's wrong. |
| Return empty results marked successful | Propagate the failure with context | It keeps the pipeline green. It converts an error into a **false finding**. |
| Terminate the workflow on one subagent failure | Proceed with partial results, annotate the gap | Fail-fast is a good instinct. It discards everything that succeeded. |
| Ship a synthesis with no coverage section | State well-supported vs gaps and why | The report reads cleanly. "No evidence found" and "we never looked" render identically. |
| Read the whole codebase upfront | Grep entry point → Read → follow imports | Thorough. Context is gone before reasoning starts. |
| Keep exploring in one long session | Scratchpad file + phase summaries | Continuity feels valuable. The model starts citing "typical patterns" instead of what it found. |
| Restart a crashed exploration from zero | State manifests the coordinator reloads | Nothing was persisted, so there's no choice — which is the point of building it beforehand. |
| Automate on 97% aggregate accuracy | Segment by document type **and** field | One number, clearly above threshold. A 61%-accurate segment hides inside it. |
| Sample low-confidence extractions to measure quality | **Stratified** sample of the **high**-confidence set | You're checking the risky ones. You learn nothing about what you're auto-approving. |
| Simple random sampling | Stratified | Statistically respectable. It spends the budget on the majority segment and may draw *zero* from the failing one. |
| Pick a confidence threshold that "feels right" | Calibrate on a labelled validation set | 0.8 sounds high. The mapping from confidence to error rate is not guessable. |
| Route to human on low confidence only | Low confidence **or** ambiguous source | Confidence covers uncertainty. The model can be confident while reading a contradictory document. |
| Pick the more credible source when two conflict | Report **both** with attribution and methods | You're exercising judgment. You're destroying information and presenting contested data as settled. |
| Average two conflicting figures | Report both | It's a compromise. It produces a number nobody measured. |
| Treat two figures for one metric as a contradiction | Check the **dates** — it may be a trend | They disagree, plainly. 2023 vs 2025 is a time series. |
| Render everything in one uniform format | Tables for financial, prose for news, lists for technical | Consistency looks professional. A table of paragraphs is worse than either form. |
| Subagent resolves a conflict it found | Annotate both; the **coordinator** reconciles | It has the documents in front of it. It lacks the context, and its decision never appears in a log. |

---

## The seven meta-patterns

If you're stuck between two options, these resolve most items:

1. **Deterministic beats probabilistic when consequences are real.** Money,
   compliance, identity → hooks and code gates, never prompt instructions.
2. **Fix the root cause, and prefer the cheapest sufficient fix.** The exam
   repeatedly says "most effective *first* step." Descriptions before few-shot;
   prompts before classifiers.
3. **Self-report is not a measurement.** Confidence scores, "I'm done", "this is
   complex" — all rejected as control signals. Use observable properties.
4. **Never silently discard information.** Suppressed errors, averaged conflicts,
   dropped attribution, unannotated coverage gaps — all wrong for the same reason.
5. **Context is a budget with a correctness cost.** Trim at the boundary, delegate
   verbose work, persist findings externally. Degradation causes wrong answers,
   not just expensive ones.
6. **More capacity ≠ better attention.** Bigger context windows do not fix
   dilution. Split the passes.
7. **When output is systematically wrong but every component succeeded, look
   upstream at the decomposition.** (Sample Q7.)
