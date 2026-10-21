---
name: analyze-paper
description: Analyze complete supplied Markdown papers through DeepAgents typed reader tasks; extract source-linked findings, limitations, counterevidence and question dispositions.
---

# analyze-paper

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

Read [the scientific record contract](references/scientific-records.md) for
`scientific-source/1` input and `scientific-record/1` output. Use role `reader`.
Read the complete original source, including tables, notes and late limitations.
Return content-specific observations for all parts, findings across all nine
fields, evidence selections, explicit obligations and every question disposition.
Submit exactly the supplied `data` schema; do not add note fields or fabricate IDs.
Reader acceptance remains unverified extraction, not approval of later writing.

Standalone entry: `scripts/native_task.py --role reader --input SOURCE_PACKET.json
--out NEW_RUN --skills-root SKILLS_ROOT --tokenizer TOKENIZER.json`.
The input must be built with `scientific_records.source_packet`, not raw Markdown.
