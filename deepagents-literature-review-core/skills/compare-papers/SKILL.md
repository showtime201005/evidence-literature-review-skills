---
name: compare-papers
description: Compare supplied papers or qualified evidence cards through DeepAgents typed comparer tasks, preserving compatible metrics, scope, counterevidence and traceable premises.
---

# compare-papers

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

Read [the mapped comparison contract](references/mapped-drafts.md). Use role
`comparer` with a supplied `review-draft-packet/1`, kind `comparison`.
Compare actual source materials or complete direct-premise claims; metadata and
child receipts are not additional scientific evidence. Cover every assigned
paper/dimension cell and research question. Preserve differing populations,
metrics, conditions, uncertainty, counterevidence and explicit retention decisions.
Submit claims, grouped retention and cells through the actual supplied tool schema.
In v2, require qualified child closure before creating downstream conclusions.

Standalone entry: `scripts/native_task.py --role comparer --input COMPARISON_PACKET.json
--out NEW_RUN --skills-root SKILLS_ROOT --tokenizer TOKENIZER.json`.
