# Practice Questions — CCAR-F

30 questions in the exam's format, weighted to the blueprint (D1 27% · D2 18% ·
D3 20% · D4 20% · D5 15%). These are **new** — none duplicates the 12 samples in
the official guide, though several probe the same objectives from a different
angle.

Each is grounded in one of the six exam scenarios. Answers and rationales are at
the bottom. Every item states how many responses to select, as the real exam does.

**How to use this:** answer all 30 cold, then read the rationales for the ones you
got wrong *and* the ones you got right for the wrong reason. The rationale for
every distractor is included, because on this exam the distractors are where the
learning is — they are all real practices, just not the answer to the question
asked.

---

## Domain 1 — Agentic Architecture & Orchestration

**Q1.** *(Scenario: Customer Support Resolution Agent)* Select ONE.

Your agentic loop terminates when the response contains a text block. Production
traces show that roughly one conversation in six ends with the customer receiving
a message like "Let me look that order up for you" and nothing further. The tools
were never executed. What is the fix?

A. Increase `max_tokens` so the model can finish its response.
B. Add a system prompt instruction: "Do not respond with text until you have
   finished using all necessary tools."
C. Terminate on `stop_reason == "end_turn"` and continue while it is `"tool_use"`.
D. Set `disable_parallel_tool_use: true` so only one tool is requested per turn.

---

**Q2.** *(Scenario: Multi-Agent Research System)* Select ONE.

Your coordinator delegates to four subagents. Latency is roughly the sum of the
four subagent runtimes, and you expected it to be closer to the longest one. The
coordinator's `allowed_tools` includes `"Task"` and every subagent completes
successfully. What is the most likely cause?

A. The subagents are configured with `model: "sonnet"` instead of a faster model.
B. The coordinator is emitting one `Task` call per response across four turns
   rather than four `Task` calls in a single response.
C. Subagent context isolation forces each one to re-read shared documents.
D. The coordinator is running with too low a `max_turns` limit.

---

**Q3.** *(Scenario: Customer Support Resolution Agent)* Select TWO.

You must guarantee that `process_refund` is never called for more than $500
without human approval. The business has a compliance audit in six weeks. Which
TWO approaches satisfy the requirement?

A. Add "NEVER issue a refund over $500 without approval" to the system prompt in
   capital letters.
B. Implement a `PreToolUse` hook that returns `permissionDecision: "deny"` with a
   reason directing the agent to the escalation workflow.
C. Add a check inside the tool implementation itself that rejects amounts over
   $500 with a structured business error.
D. Add three few-shot examples showing the agent escalating large refunds.
E. Set `tool_choice: {"type": "tool", "name": "escalate_to_human"}` on every
   request where the order total exceeds $500.

---

**Q4.** *(Scenario: Multi-Agent Research System)* Select ONE.

A research run on "the effect of automation on skilled trades" produces a report
covering only electrical and plumbing work. The web search agent returned
relevant sources for everything it was asked. The document analyst summarised
correctly. The synthesis agent produced coherent, well-cited output. Coordinator
logs show three subtasks: "automation in electrical contracting", "automation in
plumbing", "automation in HVAC installation". What do you fix?

A. The synthesis agent, which should detect and report coverage gaps.
B. The web search agent's queries, which need to be broader.
C. The coordinator's task decomposition, which does not span the topic.
D. The document analyst's relevance criteria, which are filtering too aggressively.

---

**Q5.** *(Scenario: Developer Productivity)* Select ONE.

An engineer resumes a named investigation session from last week to continue
tracing a refund bug. Since then, three of the eleven files analysed have been
refactored. What is the most reliable approach?

A. Start a fresh session — any stale tool results make the prior context unusable.
B. Resume the session and tell it explicitly which three files changed, instructing
   it to re-read those.
C. Resume the session normally; the agent will re-read files as needed.
D. Fork the session so the stale analysis is preserved on a separate branch.

---

**Q6.** *(Scenario: Customer Support Resolution Agent)* Select ONE.

Your MCP tools return timestamps in three formats: Unix epoch from the orders
service, ISO 8601 from shipping, and `DD/MM/YYYY` strings from the legacy returns
system. The agent occasionally reports a return date months off. What is the most
robust fix?

A. Add a system prompt section explaining each service's date format.
B. Add few-shot examples showing correct interpretation of each format.
C. Implement a `PostToolUse` hook that normalises all timestamps to ISO 8601
   before the model sees them.
D. Ask each backend team to standardise on ISO 8601.

---

**Q7.** *(Scenario: Developer Productivity)* Select ONE.

Your agent must evaluate two competing refactoring strategies against the same
codebase analysis, which took eleven minutes and 40k tokens to produce. You want
both evaluations grounded in that analysis, and you do not want the first strategy
explored to influence the second. What do you use?

A. Run both evaluations in one session, asking for a comparison at the end.
B. Run the analysis twice, once per strategy, in two independent sessions.
C. Fork the analysis session twice using `fork_session`.
D. Resume the analysis session sequentially for each strategy.

---

**Q8.** *(Scenario: Multi-Agent Research System)* Select ONE.

Your coordinator's system prompt reads: "STEP 1: call the search agent. STEP 2:
call the document analyst. STEP 3: call the synthesis agent. STEP 4: return the
result." A user asks "what year was the Musicians Union founded?" What is the
primary problem?

A. The coordinator cannot handle a query that needs no research.
B. The pipeline always runs all three subagents regardless of query complexity,
   and the procedural framing prevents subagents from adapting.
C. `allowed_tools` probably does not include `"Task"`.
D. The synthesis agent will hallucinate because it has only one finding.

---

## Domain 2 — Tool Design & MCP Integration

**Q9.** *(Scenario: Structured Data Extraction)* Select ONE.

Two tools: `parse_document` ("Parses a document and returns its contents") and
`read_file` ("Reads a file and returns its contents"). The agent selects between
them unpredictably for identical requests. What is the most effective first step?

A. Merge them into a single `load` tool.
B. Rewrite both descriptions to state accepted input types, what each returns, and
   an explicit boundary naming when to use the other.
C. Remove `parse_document` and let the agent parse the raw text itself.
D. Add few-shot examples of correct selection to the system prompt.

---

**Q10.** *(Scenario: Customer Support Resolution Agent)* Select ONE.

`lookup_order` returns `{"error": "Operation failed"}` for every failure mode:
gateway timeouts, malformed order IDs, orders outside the caller's account, and
orders archived after 24 months. Production shows the agent retrying all four, up
to its iteration cap. Which change most improves recovery behaviour?

A. Increase the iteration cap so retries have a chance to succeed.
B. Return `errorCategory` (transient / validation / permission / business) plus an
   `isRetryable` boolean and a human-readable message.
C. Instruct the agent in the system prompt to retry at most twice per tool.
D. Have the tool raise an exception instead of returning an error object.

---

**Q11.** *(Scenario: Developer Productivity)* Select TWO.

A teammate reports that the Jira MCP tools your team relies on are unavailable in
their Claude Code session, while they work for everyone else. Which TWO are
plausible causes?

A. The Jira server is configured in `~/.claude.json` on the machines where it works.
B. `.mcp.json` is present but the teammate has not set the `JIRA_API_TOKEN`
   environment variable that the config expands.
C. Tools from multiple MCP servers cannot be available simultaneously, so another
   server is taking precedence.
D. The teammate's `CLAUDE.md` does not reference the Jira tools.
E. The teammate is running with `strict_mcp_config` enabled and a config that omits
   the Jira server.

---

**Q12.** *(Scenario: Multi-Agent Research System)* Select ONE.

Your synthesis agent has access to all 18 tools in the system so it "has what it
needs." Evaluation shows it issuing web searches and re-reading source documents
rather than synthesising the findings it was given. What is the correct change?

A. Add a system prompt instruction: "Do not search; only synthesise the findings
   provided."
B. Restrict the synthesis agent to its role's tools, plus one scoped `verify_fact`
   tool for simple checks, routing complex verification through the coordinator.
C. Remove all tools from the synthesis agent.
D. Increase the detail in the findings passed to the synthesis agent so it has no
   reason to search.

---

**Q13.** *(Scenario: Developer Productivity)* Select ONE.

An agent must find every place a deprecated `LegacyClient` class is instantiated
across a 900-file repository, including through two wrapper modules that re-export
it under different names. What is the most reliable approach?

A. `Glob **/*.py` then `Read` each file.
B. `Grep` for `LegacyClient`, then report the matches.
C. `Grep` for `LegacyClient` to find the class and its re-exports, collect every
   exported alias, then `Grep` for each alias.
D. `Bash` with `find . -name "*.py" -exec grep -l LegacyClient {} \;`.

---

## Domain 3 — Claude Code Configuration & Workflows

**Q14.** Select ONE.

Your monorepo has Go services, a React frontend, and Terraform infrastructure.
Each area has distinct conventions. Terraform files live under `terraform/`, Go
under `services/`, but React component tests (`*.test.tsx`) sit beside their
components throughout `apps/`. You want conventions applied automatically. What is
the most maintainable configuration?

A. One root `CLAUDE.md` with a section per area.
B. A `CLAUDE.md` in `terraform/`, one in `services/`, one in `apps/`.
C. `.claude/rules/` files with `paths` frontmatter globs for each convention set.
D. Skills in `.claude/skills/` for each area, invoked as needed.

---

**Q15.** Select ONE.

A skill that maps unfamiliar codebase areas produces 40+ tool calls of `Grep` and
`Read` output. Developers complain that after invoking it, the main conversation
has no room left for the actual task. Which frontmatter option addresses this?

A. `allowed-tools: Read, Grep, Glob`
B. `argument-hint: [module name]`
C. `context: fork`
D. `description: ...`

---

**Q16.** Select ONE.

Your CI job runs `claude -p "$(git diff origin/main...HEAD)" > review.txt` and a
Python script regex-parses `review.txt` to post PR comments. It worked for two
months, then started posting malformed comments after no change to the pipeline.
What is the underlying design problem?

A. `-p` should be `--print` for stable output.
B. The review output is unstructured prose, so any change in the model's formatting
   breaks the parser.
C. `git diff` output exceeds the context window.
D. The job needs `--output-format stream-json` to be reliable.

---

**Q17.** Select ONE.

Your team's automated PR review re-posts the same eight comments on every push.
Developers have started ignoring the bot. What is the correct fix?

A. Only run the review on the first push to a PR.
B. Raise the severity threshold so fewer comments are posted.
C. Include the prior findings in context and instruct Claude to report only new or
   still-unaddressed issues.
D. Deduplicate comments in the posting script by comparing comment text.

---

**Q18.** Select ONE.

An engineer is asked to migrate a library used in 45 files, where two migration
approaches exist with different transitive dependency implications. Which approach
best fits?

A. Direct execution — the migration is mechanical once the target API is known.
B. Plan mode throughout, including the file edits.
C. Plan mode to explore dependencies and choose the approach, then direct execution
   to implement the agreed plan.
D. Direct execution, switching to plan mode if unexpected dependencies surface.

---

**Q19.** Select ONE.

A developer describes a data transformation in prose. Three attempts produce three
different interpretations of how to handle rows with null values in the join key.
What is the most effective next step?

A. Restate the prose requirement with more detail and emphasis.
B. Provide 2–3 concrete input/output examples, including a row with a null join key.
C. Ask Claude to explain its interpretation before implementing.
D. Add "handle null values correctly" to `CLAUDE.md`.

---

## Domain 4 — Prompt Engineering & Structured Output

**Q20.** *(Scenario: Structured Data Extraction)* Select ONE.

Your extraction schema marks `contract_end_date` as required. Auditors find that
14% of extracted contracts have an end date that appears nowhere in the source
document. What is the fix?

A. Add "do not guess dates" to the system prompt.
B. Make `contract_end_date` nullable and state in its description that it should be
   null when absent, and must not be inferred.
C. Add a validation step that rejects dates more than five years out.
D. Increase the model's effort level so it reads more carefully.

---

**Q21.** *(Scenario: Structured Data Extraction)* Select ONE.

You use `tool_use` with a strict JSON schema for invoice extraction. Zero parse
errors in 30,000 documents. Finance reports that 3% of extracted invoices have a
total that does not equal the sum of their line items. What does this tell you?

A. The schema is not strict enough and needs `additionalProperties: false`.
B. Tool use eliminates syntax errors but not semantic errors; you need explicit
   validation of cross-field relationships.
C. The model needs a higher `max_tokens` to complete extraction.
D. Line items should be a string rather than an array.

---

**Q22.** *(Scenario: Claude Code for CI)* Select ONE.

Your review prompt says "only report issues you are highly confident about."
Precision has not improved and recall has dropped noticeably. Why?

A. The model's confidence is well calibrated, so it is correctly filtering.
B. Confidence-based instructions ask the model to introspect rather than apply a
   checkable criterion, so they suppress findings without improving accuracy.
C. `max_tokens` is truncating the findings list.
D. The instruction should be placed at the end of the prompt rather than the start.

---

**Q23.** *(Scenario: Structured Data Extraction)* Select TWO.

You are processing 80,000 archived contracts for a compliance review due in three
weeks. Which TWO decisions are appropriate?

A. Use the Message Batches API for the 50% cost reduction.
B. Use the synchronous API to guarantee completion time.
C. Refine the extraction prompt on a 100-document sample before submitting the
   full volume.
D. Submit all 80,000 in one batch and retry the entire batch if any request fails.
E. Use the Batches API with a multi-turn tool-calling loop for documents needing
   clarification.

---

**Q24.** *(Scenario: Structured Data Extraction)* Select ONE.

Your validation-retry loop retries any extraction that fails schema validation, up
to three times. Cost analysis shows 22% of total spend goes to retries, and the
`vendor_tax_id` field accounts for most of them — it is absent from about a fifth
of documents. What should change?

A. Increase retries to five so more eventually succeed.
B. Make `vendor_tax_id` nullable and stop retrying when the information is absent
   from the source.
C. Lower the retry limit to one.
D. Add a few-shot example showing tax ID extraction.

---

**Q25.** *(Scenario: Claude Code for CI)* Select ONE.

Your pipeline generates code, then in the same session asks Claude to review it
before opening the PR. Reviewers keep finding issues the self-review missed. What
is the most effective architectural change?

A. Instruct the review step to "be extremely critical and assume the code is wrong."
B. Enable extended thinking on the review step.
C. Run the review in a separate instance with no access to the generation session.
D. Run the review three times and report issues appearing in at least two runs.

---

## Domain 5 — Context Management & Reliability

**Q26.** *(Scenario: Customer Support Resolution Agent)* Select ONE.

In conversations exceeding 30 turns, your agent begins giving vague answers about
amounts and dates it was told earlier, and occasionally states figures that were
never mentioned. Your harness progressively summarises older turns. What fixes it?

A. Increase the summarisation threshold so more turns stay verbatim.
B. Extract transactional facts (amounts, dates, order IDs, commitments) into a
   structured block re-injected on every request, outside the summarised history.
C. Instruct the model not to state figures it is unsure about.
D. Switch to a model with a larger context window.

---

**Q27.** *(Scenario: Multi-Agent Research System)* Select ONE.

A subagent's document search times out after three internal retries. It had
already retrieved four relevant sources before the timeout. What should it return
to the coordinator?

A. An empty result set marked successful, so the workflow continues.
B. `{"status": "search unavailable"}` after the retries are exhausted.
C. Structured context: failure type, the query attempted, the four partial results,
   suggested alternatives, and the resulting coverage gap.
D. Raise the timeout exception so the coordinator's handler terminates the run.

---

**Q28.** *(Scenario: Structured Data Extraction)* Select ONE.

Your extraction pipeline reports 96.4% field-level accuracy on a labelled set, and
you plan to reduce human review to a 5% spot check. What must you verify first?

A. That the 96.4% figure is statistically significant at the population size.
B. That accuracy holds across every document type and every field, since a small
   low-accuracy segment barely moves the aggregate.
C. That the model's confidence scores exceed 0.9 on the labelled set.
D. That the 5% spot check is drawn uniformly at random.

---

**Q29.** *(Scenario: Multi-Agent Research System)* Select ONE.

Two credible sources report different market-size figures for the same year: $4.1B
from an industry association and $2.8B from a government statistics office. What
should the synthesis agent do?

A. Report the more authoritative source's figure, noting the other exists.
B. Report the range, $2.8B–$4.1B.
C. Report both figures with source attribution and their differing methodologies,
   in a section distinguishing contested from well-established findings.
D. Average them and note the uncertainty.

---

**Q30.** *(Scenario: Developer Productivity)* Select TWO.

An agent has been exploring a large monorepo for two hours. It now gives
inconsistent answers about classes it identified earlier and refers to "typical
patterns in codebases like this" instead of specific findings. Which TWO address
this?

A. Have the agent maintain a scratchpad file of key findings and consult it for
   subsequent questions.
B. Increase `max_turns` so it can re-explore.
C. Delegate verbose exploration to subagents so the main context holds only
   summaries.
D. Instruct the agent to be more specific in its answers.
E. Switch to a model with a larger context window.

---
---

# Answers and Rationales

**Q1 — C.** Loop control flow is driven by `stop_reason` and nothing else. Claude
frequently emits a text block *and* a `tool_use` block in the same response, so
"contains text" terminates mid-task. **A** misreads the symptom — the response is
complete, the loop is wrong. **B** is probabilistic and also fights a behaviour
(narrating before acting) that is desirable. **D** reduces parallelism without
affecting termination.

**Q2 — B.** Parallel spawning means emitting multiple `Task` calls in a *single*
response. One per turn serialises them, so latency becomes the sum. **A** is a
per-agent speed question, not the ×4 factor described. **C** is real but would
show as token cost, not serialised latency. **D** would truncate the run, not
slow it.

**Q3 — B and C.** Both are programmatic and deterministic. **B** blocks the call
before execution *and* redirects to escalation via the reason string; **C**
enforces at the tool boundary so the rule holds no matter what calls it. **A** and
**D** are probabilistic — non-zero failure rate, and unshowable to an auditor.
**E** forces escalation on every request over $500 regardless of whether a refund
was requested, breaking every large-order conversation.

**Q4 — C.** The subagents all executed their assignments correctly; the topic was
decomposed into three subtopics that omit carpentry, welding, masonry and the
rest. This is the Sample Q7 pattern: when output is systematically incomplete but
every component succeeded, look upstream at decomposition. **A**, **B** and **D**
blame agents working correctly within their assigned scope.

**Q5 — B.** Most of the prior context is still valid; only three of eleven files
moved. Naming them gives targeted re-analysis without discarding the other eight
files' work. **A** overcorrects — full re-exploration is the expensive answer for
broadly stale context, not three files. **C** relies on the agent spontaneously
doubting its cache, which is intermittent. **D** misuses forking, which is for
divergent exploration from a shared baseline, not staleness.

**Q6 — C.** Date normalisation is a deterministic transform, so it belongs in
code. A `PostToolUse` hook rewrites the result before the model sees it, removing
the interpretation step entirely. **A** and **B** are probabilistic and fail
silently — a wrong date reaches the customer with no error. **D** is correct
long-term and does not help you this quarter; the exam asks for the robust fix
available to *you*.

**Q7 — C.** Forking twice gives both branches the same expensive baseline while
keeping them isolated, so neither anchors the other. **A** contaminates: the first
strategy explored influences the second. **B** pays for the eleven-minute analysis
twice. **D** is sequential in one session — same contamination as A.

**Q8 — B.** The fixed pipeline runs all three subagents for a query needing none,
and the STEP-by-STEP framing gives subagents a procedure rather than a goal, so
they cannot adapt. The fix is dynamic selection plus goal-and-quality-criteria
prompting. **A** is a symptom of B, not the underlying problem. **C** contradicts
the premise (delegation is happening). **D** is speculative.

**Q9 — B.** Descriptions are the primary tool-selection mechanism, and these two
are functionally indistinguishable as written. Add accepted inputs, returns, and
an explicit boundary. **A** is a legitimate architecture change but far more than
a *first step*. **C** discards a capability to avoid a description problem. **D**
adds per-request tokens without fixing the root cause — the Sample Q2 distractor.

**Q10 — B.** Structured error metadata lets the agent retry transients, correct
validation errors, stop on permission errors, and explain business errors. **A**
increases the cost of the wrong behaviour. **C** is probabilistic and still cannot
distinguish the categories. **D** loses the ability to hand a structured,
recoverable result back to the model.

**Q11 — A and E.** **A** is the classic scope bug: user-scoped config works
locally and never travels. **E** is a genuine cause — strict mode ignores
file-based configuration entirely. **B** is wrong as stated: a missing env var
would cause an *authentication* failure, not the tools being absent. **C** is
false — all configured servers are available simultaneously. **D** confuses
CLAUDE.md with tool availability.

**Q12 — B.** Scoped tool access per role, with a narrow cross-role tool for the
high-frequency simple case. **A** is prompt-based and the tools remain reachable.
**C** removes the legitimate 85% case and forces every trivial fact-check through
a coordinator round trip. **D** is speculative caching — you cannot predict what
it will want to verify.

**Q13 — C.** Two-step search: find the exported names first, then search each
alias, or you miss every call site that only uses the wrapper name. **A**
exhausts context on 900 files. **B** misses the re-exported aliases — the exact
trap in the question. **D** is Bash reimplementing Grep, losing structured
results and the permission surface.

**Q14 — C.** Glob-based path rules handle both directory-bound conventions
(`terraform/**`) *and* file-type conventions scattered across directories
(`**/*.test.tsx`) in one mechanism, loading only when relevant. **A** relies on
inference and pays for every rule on every request. **B** cannot express the
scattered test files. **D** requires invocation, contradicting "automatically."

**Q15 — C.** `context: fork` runs the skill in an isolated sub-agent context so
its verbose output never enters the main conversation. **A** restricts tools,
which is good practice but does not reduce output volume. **B** and **D** are
unrelated to context consumption.

**Q16 — B.** Regex over prose is coupled to formatting the model was never asked
to keep stable. Use `--output-format json` with `--json-schema` to make the shape
a contract. **A** is cosmetic — they are the same flag. **C** would produce a
different failure and does not match "worked for two months." **D** is a streaming
format for a different purpose.

**Q17 — C.** The review has no memory across runs, so it re-derives the same
findings. Supplying prior findings plus a "only new or unaddressed" instruction
is the documented fix. **A** abandons review on subsequent pushes, where
regressions are introduced. **B** hides real findings. **D** breaks the moment
wording shifts slightly, and does not stop the model spending tokens re-finding
them.

**Q18 — C.** Plan mode for the architectural decision (two approaches, different
dependency implications, 45 files), then direct execution once the approach is
agreed. **A** ignores a genuine architectural choice. **B** never implements
anything. **D** waits to discover complexity that the question already states.

**Q19 — B.** Concrete input/output examples are the most effective technique when
prose is being interpreted inconsistently — and the example must include the
ambiguous case (the null join key). **A** repeats the failing approach. **C** (the
interview pattern) is useful when *you* have not decided; here you have, and the
model just needs to see it. **D** puts a vague instruction in a file loaded on
every request.

**Q20 — B.** A required field the source often lacks is pressure to fabricate.
Nullable plus an explicit "return null, do not infer" instruction removes it.
**A** alone leaves the schema demanding a value. **C** catches only implausible
dates, not plausible invented ones. **D** does not address the structural
incentive.

**Q21 — B.** Schemas constrain shape, not meaning. Zero parse errors and 3%
arithmetic failures is exactly the expected signature. Add cross-field validation
— ideally by extracting `calculated_total` alongside `stated_total` with a
conflict flag. **A** hardens shape further, which is already fine. **C** would
show as truncation. **D** discards structure for no benefit.

**Q22 — B.** "Highly confident" asks the model to introspect on a poorly
calibrated internal signal, so it reports less without reporting better. Replace
with categorical criteria about the *code*. **A** contradicts the observed
outcome. **C** would truncate mid-list, a different symptom. **D** is prompt
positioning, not the mechanism.

**Q23 — A and C.** Three weeks is comfortably latency-tolerant, so batch is right
and halves the cost. Refining on a sample first maximises first-pass success,
which dominates total batch cost. **B** forfeits the saving for a guarantee not
needed. **D** re-pays for everything that succeeded — resubmit only failed
`custom_id`s. **E** is impossible: the Batches API does not support multi-turn
tool calling within a request.

**Q24 — B.** The information is absent from the source, so no retry can converge —
this is the documented limit of retry. Make the field nullable and route absent
values onward. **A** multiplies wasted spend and increases the odds of eventual
fabrication. **C** reduces cost but still retries an unconvergeable case and now
also gives up early on genuinely fixable format errors. **D** cannot conjure a
tax ID that is not in the document.

**Q25 — C.** A session that generated code retains the reasoning that produced it
and is less likely to question its own decisions. An independent instance is the
documented fix, and it beats both self-review instructions and extended thinking.
**A** and **B** leave the contaminating context in place. **D** requires consensus,
which suppresses subtle findings caught by only one run.

**Q26 — B.** Progressive summarisation reliably destroys numbers, dates and
stated commitments while preserving the emotional gist. A persistent case-facts
block kept outside the summarised history is the fix. **A** delays the problem.
**C** is probabilistic and does not restore lost data. **D** postpones it at cost
and does not address summarisation.

**Q27 — C.** Structured error context lets the coordinator retry with a modified
query, route around, or proceed with partial results and annotate the gap. Note
that the *local retries were correct* — the error is in what gets returned
afterwards. **A** converts a failure into a false finding. **B** is the Sample Q8
distractor: right retry behaviour, then discards the four sources and the attempted
query. **D** terminates a run in which other agents succeeded.

**Q28 — B.** Aggregate accuracy hides segment failure; a small segment at 60% is
nearly invisible in a 96.4% average and is the only thing that should stop you.
Validate by document type *and* field. **A** misses the point — the number can be
perfectly precise and still misleading. **C** confuses confidence with accuracy.
**D** is wrong twice over: the spot check should be *stratified*, not uniform, or
it will barely sample the failing segment.

**Q29 — C.** Conflicting figures from credible sources are information. Report
both with attribution and methodology, in a section separating contested from
well-established findings. **A** makes an editorial decision the reader cannot
audit. **B** presents a range as if one continuous estimate were measured. **D**
produces a number nobody measured.

**Q30 — A and C.** Scratchpad files persist findings across context degradation,
and delegating verbose exploration keeps the main context for coordination. **B**
adds more of the exploration that caused the problem. **D** addresses the symptom
with an instruction. **E** delays onset without preventing degradation — this is a
context *quality* failure, not purely a capacity one.

---

## Scoring

| Score | Reading |
|---|---|
| 27–30 | Comfortable. Focus remaining time on the two or three objectives you missed. |
| 22–26 | On track. Re-read the rationales for every miss, then re-run the lab modules for those task statements. |
| 17–21 | Work the anti-pattern table until the "why it's tempting" column is predictable. |
| < 17 | Run the lab modules end to end before attempting these again — the empirical demos land better than the prose. |

Note which *kind* of error you make. Confusing two mechanisms (rules vs directory
CLAUDE.md) is a knowledge gap and is fixed by reading. Picking a good practice
that does not answer the question asked (few-shot for a description problem,
consensus voting for false positives, a bigger context window for attention
dilution) is a judgment gap — and that is the one this exam is built to test.
