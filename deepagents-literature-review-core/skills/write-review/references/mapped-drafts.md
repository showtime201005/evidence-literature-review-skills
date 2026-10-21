# Native mapped draft profile

Use this profile only when the task supplies `review-draft-packet/1` and the
typed `DraftSubmission` tool. It replaces the legacy CLI output contract for
this task. Submit through the supplied tool; the runtime owns rendering and IDs.

The input may use lossless `review-draft-wire/1`. Its `packet` contains all
non-source fields of the canonical packet. `source_encoding.paper_versions`
rows use the named `paper_version_columns`; each source table row follows its
`columns`. Resolve `paper_version_index` to that paper/version pair, then the
row's `part_id` gives the original `paper_id/part_id` reference. Byte offsets,
full text (direct cards) or text hashes (synthesis), and every other row value
are preserved exactly. `canonical_sha256` binds the reconstructed full packet.
Do not submit this wire encoding: submit the ordinary typed DraftSubmission.
Synthesis contains all source references used by actual direct premise claims;
unreferenced part metadata remains in the source archive.

For `paper_card`, write a concise but substantive evidence card covering design,
contribution, relevant outcomes and uncertainty, applicability and limitations.
Use at most 12 claim paragraphs and 3000 total Unicode characters of claim text;
aim for 6–10 paragraphs and 1200–2200 characters in Traditional Chinese. Raw
extraction remains archived. Do not translate the paper paragraph by paragraph.
Prioritize question-relevant results, intervals, null/adverse findings, persistent
failures, missing measurements and applicability. Explain why omitted background
or redundant details do not change the answer in retention dispositions. Never
truncate an oversized draft or drop material counterevidence to meet the limit;
rewrite it completely. Independent review still checks important omissions.
For `synthesis`, answer the research questions using the actual supplied premise
claims. Explain agreements, disagreements, shared study data, evidence gaps and
conditions. Distinguish a gap in this supplied corpus from a gap in the field.

Every scientific paragraph is a claim with a unique local ID, plain text without
line breaks, source references `paper_id/part_id`, question IDs, attribution and
the exact paper population it describes. Separate compound claims when their
support differs. A citation is not evidence for every clause merely because it
mentions the same topic. Do not insert headings, links or bibliography into text.
Check the declared locators against every factual clause before submitting:
support in a different part does not validate the cited part. Event order,
frequency, causal direction and population restrictions need explicit support;
do not infer them merely because two facts appear together in the source.

Preserve epistemic strength in the claim itself: "suggests", "may", "is
consistent with" and "was observed" are not interchangeable with "demonstrates"
or "causes". Qualitative mechanism interpretations must retain their uncertainty
and attribution. A caveat elsewhere in the card does not repair an overconfident
claim. Omit an unstated event ordering instead of filling it from narrative order
or a plausible workflow; two events preceding a third do not establish an order
between those two events.

For synthesis, cite actual `section_id/local_id` premise claims. Source metadata
is a locator, not original text or additional evidence: do not infer findings
from source offsets or hashes. The conclusion's population and source references
must be supported by those premises. Use `analyst_inference` for derived
interpretations, retaining uncertainty and competing explanations.

Give each supplied retention obligation exactly one explicit disposition.
When `reader_context_profile` is `reader-finding-context/1`, `reader_findings`
contains each original complete finding once, with its actual `source_refs`,
source version and reader-record hash. Resolve an obligation's `finding_id` to
that exact text before choosing destination claims. A source part may support
several different findings; its topic alone does not identify the required
proposition. Reader findings remain unverified extraction, so assess the complete
original sources rather than treating this context as scientific approval.
For synthesis, these are runtime-derived `premise_retention` obligations, one
per actual direct premise claim. Their `premise_claim_id` and full `text` identify
what must be retained or explicitly excluded. An included decision must name a
delivered claim that actually lists that premise ID. The lower level's retention
entries keep their original IDs as historical evidence; they are not additional
current-task aliases. Original reader obligations remain fully checked at source
leaves (cards, or legacy direct-source comparisons), with mandatory independent
source and assembly proof closure. Comparisons derived from actual cards retain
their direct premise claims instead of repeating the original extraction duties.
`included` names delivered claims that actually retain the qualification;
`excluded` needs a scientific relevance reason. Saving a limitation only in the
raw artifacts does not retain it in the report.
An included mapping must point to the exact claim carrying the specific fact or
qualification, not just another claim on the same topic. If an obligation has
several material components, retain all of them or use a justified exclusion;
do not claim inclusion when only a convenient subset appears in the card.
Preserve persistent failures after mitigation, null/adverse findings, unmeasured quantities and design limits
whenever they qualify a question's answer. An independent verifier judges these
decisions. Do not self-approve exclusions or the resulting draft.

Answer every assigned question, including a scoped unresolved answer when the
evidence cannot decide it. Represent every assigned paper without asserting all
papers support the same conclusion. Use Traditional Chinese unless requested
otherwise. Leave `cells` empty for cards and synthesis.

## Grouped retention submission

When the tool schema is `GroupedDraftSubmission`, use `retention_groups` instead
of `retention`. The assigned obligation IDs `o1`, `o2`, etc. are exact runtime
aliases. Each group contains `obligation_ids`, `status`, `claim_ids`, and `reason`.
Group only obligations for which the same decision, delivered claims and reason
really apply. Cover every assigned alias exactly once. The runtime expands groups
back to individual original obligations before applying the unchanged validator.
All other claim, cell and independent verification requirements still apply.
Use the current input aliases when revising; old draft IDs do not replace them.
