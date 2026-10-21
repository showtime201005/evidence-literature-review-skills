# Scientific record review profile (version 1)

Use this profile when the runtime supplies an original `scientific-source/1`,
an unverified `scientific-record/1`, and the typed `RecordReviewSubmission` tool.
Other standalone source-review tasks keep their existing contracts.

The record may be wrapped in `scientific-record-source-spans/1`: read its `record`
object. Duplicate quote text is omitted because the full original parts are
already supplied. Resolve each evidence reference using `part_id` and UTF-8 byte
spans in that original source. Runtime checks exact lossless reconstruction and
the original record hash before delivery; no findings or qualifications are removed.

Read every original part and independently check each finding against its source
selections and necessary neighboring context. Give every finding one verdict.
Whole-part evidence is a locator; it does not imply that every assertion matches
the selected paragraph. Check numbers with population, method, units, baseline,
timepoint, uncertainty and negation. Distinguish unknown from zero, null intervals
from demonstrated benefit, and observational association from causal findings.

Check completeness against the whole original paper, not only the registered
findings or question map. Identify omitted critical limitations, adverse results,
subgroups, missing measurements and failures that persist after mitigation.
Check whether the record correctly flags these as obligations. Trace actual
issues to source part IDs and affected finding IDs where present; omitted facts
may have no existing finding ID. State a concrete correction without rewriting
the writer's record yourself.

Return all checked part IDs, every research question ID, all verdicts, a concrete
omission assessment and issues. Missing inputs or unresolved interpretation are
not passed. The runtime preserves failed verdicts and sends revisions to a writer;
do not change an honest adverse verdict merely to satisfy a tool gate.

This checks a paper record. It does not approve later synthesis, a comparison,
report wording, or a complete literature review. Each changed target needs its
own matching independent proof.
