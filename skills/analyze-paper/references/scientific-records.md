# Scientific record profile (native runtime, version 1)

Use this profile only when the assigned input declares `schema: scientific-source/1`
and the runtime provides a typed `ReaderSubmission` tool. Other inputs retain the
existing ChunkAnalysis contract. This profile combines reading, field assessment
and per-question dispositions to avoid separate full-paper model passes.

Read every `parts[].text` in order, including metadata, tables, captions, notes,
discussion, limitations and references. Return one content-specific observation
per part. The runtime verifies complete part coverage and original UTF-8 hashes;
that check does not prove comprehension.

Return source-linked findings across the nine extraction fields. Each finding has
a unique local ID, field, substantive text, attribution, and one or more exact
source selections identified by part ID. Prefer `quote: null` to bind the entire
original part: the runtime copies its exact text and byte offsets, saving output
tokens and avoiding transcription errors. Select every necessary part, including
caption/notes. This is source location only, not semantic approval. For a precise
substring, copy it verbatim as `quote`; for a repeated quote supply its character offset
inside the part. Preserve enough quotes to bind the entire assertion, including
units, caption interpretation, uncertainty, method and population. Do not infer
missing data. Bibliography entries are secondary references, not directly read
primary results.

Preserve the source's strength of evidence in each finding. A qualitative trace
that suggests a mechanism remains suggestive; it is not a measured causal effect
or a demonstrated mechanism. Keep modal words and attribution in the substantive
finding text, not only in an evidence quote or a separate limitation. Narrative
order alone does not establish event order; extract only the temporal relations
actually stated, leaving unstated relations unknown.

## Keep extraction concise without losing evidence

Part observations demonstrate coverage; findings represent distinct scientific
information. Do not create a new finding merely because another paragraph repeats
an already extracted assertion. Combine repeated statements of the same fact into
one finding within its field and retain all source selections needed to support
its qualifications. When different fields need different scientific aspects of
the same passage, state those aspects concisely instead of repeating the full
passage. Every field marked `extracted` still needs a finding in that field;
deduplication must not turn reported information into `not_reported`. Multiple
question dispositions may reference the same finding ID.

Keep genuinely different populations, outcomes, timepoints, conditions and
contradictory results distinct. In particular, do not merge an aggregate benefit
with an adverse subgroup into an unqualified positive finding. An attempted
mitigation and its persistent failure must remain explicitly represented.
Deduplication must preserve each important limitation and counterexample; it is
not a finding-count limit or permission to omit difficult evidence.

Assign every field an assessment and every research question a disposition. Refer
to local finding IDs in support/counterevidence. `not_reported` requires an actual
full-paper assessment; use `unresolved` when source information is inadequate.

Flag relevant adverse results, null results, persistent failures after attempted
mitigation, missing measurements, critical limitations and applicability as
`obligations`. These obligations survive even when they are not listed in a
question's counterevidence array. There is no fixed finding count cap; request a
bounded continuation if output capacity is inadequate. Do not send partial success.

The obligations list is a required assessment on every finding. Runtime also
retains every extracted limitation, condition, unexpected finding and question
counterevidence reference as a structural retention obligation. Those categories
do not assert scientific importance; later writers/auditors must explicitly
account for their inclusion or justified exclusion rather than silently losing them.

Preserve governing negation and attribution when extracting a subordinate
clause. "The evidence does not establish P" reports an evidentiary limitation,
not a positive finding P or proof of not-P. Quote enough of the governing clause
to preserve that scope; literal substring matching alone cannot validate meaning.

Submit exactly `{"data": {"observations": [...], "findings": [...], "fields": [...], "questions": [...]}}`
through the supplied tool. Those are the only four properties inside `data`.
Place explanations in existing `note`, `text` or `reason` properties; do not add
`fields_note`, `questions_note` or other undeclared properties.
Runtime adds execution identity, byte spans,
evidence IDs and unverified status. Neither acceptance nor these generated IDs
mean semantic verification. A fresh verifier must check source support and
important omissions before publication.
