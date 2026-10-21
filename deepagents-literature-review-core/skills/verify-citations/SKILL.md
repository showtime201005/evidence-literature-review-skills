---
name: verify-citations
description: Independently review source support, scientific qualifications, retention, omissions and integration using the DeepAgents native verification contracts.
---

# verify-citations

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

Choose the contract matching the supplied packet and tool, never by guessing:

- Scientific record review: read [record review](references/scientific-record-review.md).
- Native v1 proof / assembly: read [hierarchical proof](references/hierarchical-proof.md).
- Native v2 paper / section / closed review: read [native v2 review](references/native-review-v2.md)
  and the exact runtime-provided unit inventory and submission tool schema.

Verify actual own-declared sources, governing negation, relation/causal/temporal
strength, numeric units, populations and uncertainty. A true statement elsewhere
does not repair an incorrect citation. Check included retention against the exact
named delivered claims; a finding's own text cannot prove it survived in a draft.
Inspect important omissions and integration wherever assigned. Keep every honest
negative/unresolved result and provide concrete affected IDs and corrections.

Standalone `scripts/native_task.py --role verifier` accepts `native-proof-input/1`
only for a reconstructed dependency-free v1 source node. V2 paper, section and
closed workers are driven by the full v2 workflow or Python APIs, not standalone
native_task role names. Do not treat one accepted source task as a complete review.
