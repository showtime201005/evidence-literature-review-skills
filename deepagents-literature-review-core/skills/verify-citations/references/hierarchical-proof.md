# Hierarchical independent proof profile

For `hierarchical-proof-task/1`, use the typed `ProofSubmission` tool instead of
legacy verification commands. The runtime binds versions, coverage and actual
execution identity. Do not supply your own hashes or invent missing materials.

When `responsibility_encoding` is `proof-unit-aliases/1`, `coverage` uses short
runtime IDs. Resolve them through `responsibility_aliases` to the exact units in
the unchanged materials. Use these short IDs in checked lists, verdict unit IDs
and issue unit IDs. Keep one judgment and reason per required claim/obligation;
this encoding does not group scientific decisions. Issues against material IDs
may still use their canonical material IDs. The runtime restores canonical IDs
before its unchanged coverage, contradiction and proof validation checks.

Read every assigned material. `source` nodes check actual original text against
the draft and its context, including important omissions. `cross_group` nodes
check the new conclusion against the actual supplied premise claims: child
approvals alone do not prove a new inference. Missing premises or incompatible
settings require revision or an unresolved verdict.
For each factual clause, check the source locators actually declared by that
claim. A supporting statement elsewhere in the paper does not repair an
incorrect local citation. Do not infer a temporal order that the source does
not state. Check a retention mapping against the named delivered claims, not
against a similar topic elsewhere in the card.

Before judging a relational or qualified claim, identify separately (1) the
relation and strength actually stated by its source and (2) those asserted by
the claim. Compare their participants, direction, conditions and uncertainty.
Paragraph order and a plausible workflow are not temporal evidence. Two events
both preceding a third do not establish which of the first two came earlier.
If the source permits the opposite ordering without contradiction, an asserted
ordering is not established. Likewise, qualitative traces that "suggest" a
mechanism do not establish it as a demonstrated effect. Retain the modal strength
in the claim itself; a correct quotation or a caveat elsewhere cannot repair a
stronger assertion. Explain the missing relation or strengthened certainty in
the existing verdict reason and issue fields; do not invent a new output schema.

Inspect the governing clause around an exact quote. A subordinate statement P
inside "does not establish P" or "without claiming P" is not affirmative support
for P. Absence of evidence also does not prove not-P. Preserve the operator's
scope, attribution and epistemic limit when judging both extracted findings and
the final claim; an exact quote alone cannot establish semantic support.

`citation_view` (`proof-citation-view/1`) is a deterministic view of already
delivered materials. Its `claim_rows` put each exact claim beside only its
declared complete source parts, sliced from the hash-bound UTF-8 originals.
Use those parts to establish local citation support. Full original text and
reader/premise context remain necessary for counterevidence, omitted
qualifications and completeness; they may reveal that a claim needs revision,
but cannot silently fill a missing declared supporting locator. Check every
factual clause, including its actual temporal/causal/comparative relationship,
population, conditions, uncertainty, negation and missing measurements.

`obligation_rows` put the actual finding and disposition beside only that
disposition's `named_claims`. A qualification elsewhere in the card does not
establish preservation in those named claims. An absent claim or obligation
material is explicitly marked unavailable; do not invent it. A null disposition
does not waive a complete-source or integration duty.

Cross-group and assembly tasks may have `original_not_delivered` instead of
an excerpt. This does not claim original reading or local source approval.
Follow their actual premise/dependency contract, inspecting supplied scientific
premises and scope; missing required premises still prevent approval. Views do
not replace originals, child attestations, full-source duties, canonical hashes,
or unchanged per-unit coverage/verdict gates. Responsibility aliases still map
to the canonical unit IDs used in these views.

## Selected dependency scientific views

A material with schema `dependency-scientific-view/1` contains
`claims_by_dependency`: the exact child premise claim IDs selected for this
node. Their child source checks remain in the proof lineage. Read the complete
actual text of each selected premise and its supplied section/context; inspect
its conditions, uncertainty, counterevidence and population when assessing the
new conclusion. A child passed receipt establishes the recorded check, while
the new inference still requires this node's independent judgment.

Check every locally assigned retention obligation, including an `excluded`
disposition and its relevance reason. Evaluate whether the retained or excluded
selected meaning changes the answer misleadingly. Unselected raw child
obligations remain the responsibility of the child source/assembly lineage;
this parent task does not repeat those duties or waive their required proofs.
Use `unresolved` when a selected claim or necessary context is missing. Describe
only the reading actually performed: an original absent from this task was not
reread by this reviewer.

`assembly` and `root` nodes check the actual rendered content and supplied
research context for scope, question coverage, comparison completeness, claim
mapping and retention of counterevidence. Inspect every nonempty rendered line,
including headings. Check that narrowing or excluding a finding has not changed
the answer misleadingly. Do not redo absent source checks from memory.
The default delivered prose requested by this native workflow is Traditional
Chinese. Original sources, quotations, identifiers and technical names can keep
their original language. Flag an entire delivered narrative in another language
as a delivery issue; correct citations alone do not satisfy the writing request.

Return `checked` with all six dimensions: claims, lines, papers, questions,
cells and obligations. Return one substantive verdict per assigned claim and
obligation.
Other dimensions need only their exact `checked` entries; avoid repeating them
as verdicts. Optional verdicts are accepted only for assigned coverage units,
and a negative optional verdict also prevents a passed result.
An included obligation must actually survive in the named prose; an excluded
one needs a sound relevance justification. Audit persistent failures,
null/adverse results, unmeasured quantities, populations and uncertainty.

Synthesis `premise_retention` obligations are derived from every actual direct
premise claim, including its complete text and source references. Check whether
the upper prose preserves the relevant meaning and qualifications, not merely
whether it lists a premise ID. An exclusion must not hide contradictory results
or materially narrow the answer. Original reader obligations remain separately
covered by mandatory leaf source and assembly checks; this local responsibility
does not waive or replace that proof closure.

For problems, supply affected responsibility IDs or actual material IDs, a concrete description and
required correction. An omitted fact can be linked to the affected question,
paper or line even if it has no registered claim. Do not approve all individual
claims while ignoring an important omission. Set status to `needs_revision` or
`unresolved` when any part cannot pass. Failed verdicts are retained; do not
change them to passed merely to satisfy the tool.

## Bounded responsibility shards and complete-source duties

`review_mode` distinguishes local responsibility shards from complete-source
and integration reviews. Check exactly the assigned coverage; another shard's
coverage is not your direct responsibility. Individual line materials include
the actual rendered string and offsets. Their section context binds the real
heading, exact section hash and complete render hash; the host separately
reconstructs all nonempty lines and the immutable final delivery. Do not request
the whole repeated section/render merely because this task is a local shard.

Every paper card has a mandatory host-derived `full_source_review/<paper>`
obligation. Its source reviewer receives the complete original paper, complete
reader record and complete card with all dispositions. Read all original parts
and look for important scientific omissions, including unextracted limitations
and late counterexamples. Citation support for selected claims does not satisfy
this obligation. The independently assigned assembly reviewer checks the
complete card/reader integration against that complete-source proof and version.
Use an unresolved verdict if required complete-source inputs are missing.

An integration assembly node may have empty direct coverage because child
responsibilities already partition the actual units. It still reviews supplied
actual claims/lines for contradictions and misleading integration. Root nodes
check final scope and root text against the bounded assembly rollup; they do
not claim to have reread all raw papers. Report integration defects against
actual material IDs. Original-source closure, actual scientific premises and
independent runtime identities remain mandatory across the whole proof DAG.
