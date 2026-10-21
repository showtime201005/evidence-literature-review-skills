# Native mapped comparison profile

Use this profile only for a supplied `review-draft-packet/1` with kind
`comparison` and typed `DraftSubmission` tool. Submit through that tool instead
of the legacy CLI or ComparisonSet contract.

`review-draft-wire/1` is a lossless input encoding. `packet` retains the ordinary
non-source fields. In `source_encoding`, resolve each row's
`paper_version_index` through the named `paper_versions` columns, then read all
remaining values using its table `columns`. The row's `part_id` and resolved
paper ID form the unchanged source reference. Full source text, byte offsets
and hashes are preserved; `canonical_sha256` binds the exact reconstructed
packet. Submit the normal typed DraftSubmission, not the input wire encoding.

When actual paper-card `premises` are supplied, the comparison is derived from
those complete claim texts and their retained qualifications. Each claim must
identify its real `premise_claim_ids`; use only source locators and populations
supported by those premises. Source metadata is not original evidence. The
runtime supplies one `premise_retention` obligation per actual card claim, so
explicitly retain or justify excluding each. Original reader obligations and
whole-paper omissions remain checked at the card source layer; downstream
publication still requires that complete independent proof closure. A draft
card's structural acceptance alone is not scientific approval. If a requested
comparison dimension cannot be resolved from the supplied premises, say so
explicitly rather than inventing evidence from hashes or offsets.

Create exactly one cell for every assigned paper and dimension. Each cell names
local claim IDs whose text describes that paper's evidence for that dimension.
Use explicit unresolved statements for missing measurements; unknown does not
mean zero. Every claim carries original `paper_id/part_id` references, question
IDs, source-finding versus analyst-inference attribution, scope and exact paper
membership. No Markdown headings, links or multiline text in claims.

Retain metric definition and unit, sample/population, baseline, study design,
uncertainty and relevant conditions. Avoid ranking unlike settings as universal
superiority. Shared datasets or participants must not be counted as independent
replications. Unequal condition sets may overlap. Separate paper-specific facts
from cross-paper inference and cite all members of each claimed population.

Carry evidence strength into the comparison text. Several suggestive qualitative
accounts do not become a demonstrated mechanism merely by being grouped. Preserve
modal qualifiers in every affected claim; do not move them exclusively to a
limitations cell. Do not infer event ordering from paragraph order or invent a
relation between events that merely share the same earlier or later event.

Address every supplied research question. For each retention obligation, name
the claims retaining it or explain its exclusion explicitly. Preserve important
counterevidence, persistent failures and missing measurements in the comparison,
not just in extraction artifacts. All cells and claims remain unverified until
an independent source verifier and assembly auditor approve matching content.

## Grouped retention submission

When the tool schema is `GroupedDraftSubmission`, use `retention_groups` instead
of `retention`. The assigned obligation IDs `o1`, `o2`, etc. are exact runtime
aliases. Each group contains `obligation_ids`, `status`, `claim_ids`, and `reason`.
Group only obligations for which the same decision, delivered claims and reason
really apply. Cover every assigned alias exactly once. The runtime expands groups
back to individual original obligations before applying the unchanged validator.
All other claim, cell and independent verification requirements still apply.
Use the current input aliases when revising; old draft IDs do not replace them.
