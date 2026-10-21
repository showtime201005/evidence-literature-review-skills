---
name: compare-papers
description: Compare supplied paper analyses, evidence or external research tables across methods, results, assumptions and limitations. Use for a study comparison, evidence matrix, disagreement analysis or focused comparison update, independently of any fixed upstream workflow.
---

# Compare supplied studies

For native OpenCode or DeepAgents execution, read [native-harnesses.md](references/native-harnesses.md). This skill includes its own scripts/harness_runner.py; a standalone capability requires only this skill installation. Evidence handoffs include a readable claim/source catalog when source materials are supplied.


For comprehensive reviews and report gaps read [research-modes.md](references/research-modes.md). Use the supplied full paper/question map, including unhit and negative studies; comparison does not replace full-text reading or imply unprovided sources were searched. For bounded independent verification see verification-shards.md.

Read [interface.md](references/interface.md) and [data-dictionary.md](references/data-dictionary.md) before returning data. Use ComparisonSet v2 for evidence-backed comparisons and handoff for a readable matrix. Return TaskResult v2 with actionable issues when inputs are insufficient; never invent source evidence to satisfy a schema.

Read [contracts.md](references/contracts.md). Use the bundled scripts/litreview.py for schema and locator checks. Accept external notes, CSV and JSON as well as native PaperAnalysis. Do not require a run ID or private database. Normalize CSV with import-artifact and require source_id per row.

Obtain the comparison question and dimensions from the request or provided research config. Compare only supplied materials. If a source is not provided, return needs_source; if necessary details were not extracted, return needs_extraction. Do not initiate a full review or external lookup to fill gaps.

Create one cell for each specified paper and dimension; every paper must appear. Preserve dataset / population, setup, metric definition and unit, baseline, version, sample size where given, and limitations. Use supported, contradicted, mixed, not_addressed or unresolved. Only use not_addressed after the relevant supplied text was checked. Unknown is unresolved, not zero or absence of research.

Do not rank numbers from incompatible settings as universal superiority. Group versions and duplicated or shared study data before counting independent evidence. Preserve minority results and distinguish contradiction candidates from confirmed contradictions. Include support, counterevidence, conditions and unresolved points for cross-paper conclusions.

Inherit unverified status from external or unverified material. A schema pass, supplied "verified" column, or successful comparison does not establish semantic support. In v2, keep cell verification_status=unverified permanently; trust is represented by a separate matching ComparisonVerification. Own the comparison claims independently from final report claims. Set material_refs to these comparison-owned claim IDs. Use comparison-packet, an isolated verifier, then comparison-accept; no write-review or job is required. A change to conditions, proposition, comparability or counterevidence invalidates the comparison verification. Legacy v1 publication still follows its report-claim binding rules and is not silently upgraded.

Emit ComparisonSet v2 including declared paper_ids, dimensions, source-linked claims and fully populated cells. Specify each proposition, value, relation, structured study_conditions, comparability reason, support claim refs and counterevidence. Use typed contradiction_candidates with explicit reasons. Do not insert citation formatting into scientific comparison. Use the complete example under assets/examples and capability-check. Deliver matrix plus limitations and unresolved refs; do not run the coordinator for a standalone comparison.
