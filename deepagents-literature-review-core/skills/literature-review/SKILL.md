---
name: literature-review
description: Coordinate a corpus-only Markdown literature review with real DeepAgents task subagents, complete reading, evidence cards, comparisons, synthesis, independent review and traceable delivery.
---

# literature-review

## DeepAgents native execution

This distribution uses DeepAgents 0.7.15 typed workers and OpenRouter
`qwen/qwen3.8-27b`. Use the runtime-supplied tools, exact task inputs and
`submit_result` schema. Do not invoke legacy CLIs or external harnesses.
When acting as a coordinator, obtain ready tickets from the supplied artifact
tools and delegate their exact descriptions through the real SDK `task` tool
to the named scientific role. Independent ready tickets may be delegated in
parallel within the supplied worker and token limits. Do not invent task
identities, run workers directly, or mark work accepted yourself.

Read every assigned material; hashes and successful parsing do not establish
scientific support. Preserve negative and unresolved results, actual source
versions, uncertainty, applicability, counterevidence and missing measurements.
Do not replace a negative verdict with repeated attempts to get approval.
Use Traditional Chinese for delivered narrative unless the user requests otherwise.
The request cap is 200,000 tokens including tools, history, output and margin;
lower provider caps and the shared deadline still apply. Never truncate source
materials or invent missing evidence to fit a budget.

## Full corpus workflow

Coordinate `analyze-paper`, `write-review`, `compare-papers` and
`verify-citations` through the native runtime. Input is a new first-level directory
of 1–100 UTF-8 Markdown papers and a research-question JSON array (or an object
containing `questions`). Keep unique filename stems and use a new output directory.

The host persists sources and the versioned task DAG. Obtain ready tickets using
the supplied artifact tools; actually call SDK `task` for each scientific worker.
Return compact receipts rather than copying all source text into the coordinator.
Do not run legacy prepare/job/research/deliver commands or external searches.

For explicit experimental v2, perform full reading, paper-card writing, optional
closed local checks, complete independent paper review, comparisons and hierarchical
synthesis, and independent section review before release/export. Only qualified
current versions may flow downstream. Every paper retains full-source omission
and integration duties. Upper sections use actual direct-premise science with
required child closure, not hashes as substitutes for evidence.

Preserve raw extraction and all attempts. The current implementation shares at
most two semantic repair rounds across the entire run and may exhaust them early.
Do not bypass negative gates to deliver. Changed versions need matching fresh
qualification; prior-run accepted artifacts cannot count as a first-processing run.

The target delivery is main report, one concise evidence card per paper, comparison
tables/CSV, traceable citations and original sources, plus audit/raw records.
Use the host's exact release gate and exporter, without rewriting checked science.
V2 completion is experimental: `publication_verified=false`, `quality_validated=false`.
The 100-paper/90-minute target is not yet accepted; latest two-paper run also failed.

## Native entry

Use `scripts/native_review.py --review-protocol v2 --review-observations whole-unit
--closed-checks`, with required sources/questions/out/skills-root/tokenizer paths.
CLI default remains v1 when the protocol is omitted. `scripts/native_reading.py`
is a reading-stage entry only. See the distribution root README for a full command.
