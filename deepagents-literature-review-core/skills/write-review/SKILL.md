---
name: write-review
description: Write concise evidence cards or literature synthesis through DeepAgents typed writer tasks, with explicit claim citations and retention mappings.
---

# write-review

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

Read [the mapped writing contract](references/mapped-drafts.md). Use role
`writer` with `review-draft-packet/1`, kind `paper_card` or `synthesis`.
For each paper card, preserve design, contribution, results, uncertainty,
applicability, important limitations, adverse/null results and persistent failures.
Cards permit at most 12 claims and 3000 Unicode characters of claim text; rewrite
rather than truncate or silently omit material qualifications.
Resolve every obligation to its actual finding text before selecting the named
destination claims. For synthesis, use complete actual direct premises and their
qualifications; distinguish analyst inference from reported findings.
All drafts remain unverified until independently checked against matching versions.

Standalone entry: `scripts/native_task.py --role writer --input DRAFT_PACKET.json
--out NEW_RUN --skills-root SKILLS_ROOT --tokenizer TOKENIZER.json`.
