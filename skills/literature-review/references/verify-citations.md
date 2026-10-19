---
name: verify-citations
description: Independently verify factual claims and citations against provided source texts, including arbitrary human reports, numbered references and author-year references. Detect missing citations, undeclared claims, reversed negation, numeric misattribution and unsupported synthesis. Use without requiring a specific writer or upstream workflow.
---

# Independently verify citations

For native OpenCode or DeepAgents execution, read [native-harnesses.md](references/native-harnesses.md). This skill includes its own scripts/harness_runner.py; a standalone capability requires only this skill installation. Evidence handoffs include a readable claim/source catalog when source materials are supplied.


Read [verification-shards.md](references/verification-shards.md) for bounded/resumable source checks and assembly audit. For a shard, return VerificationSet using LOCAL offsets. For an assembly packet, use a new context distinct from writer and source verifiers, read target and all context artifacts in bounded ranges, then return AssemblyAudit v2; do not re-label a source verdict as an assembly audit. For augmentation projections also read [research-modes.md](references/research-modes.md) and check numeric metric/unit/population requirements, unresolved reasons and the proposed patch, without endorsing quoted original report context.

Read [interface.md](references/interface.md) and [data-dictionary.md](references/data-dictionary.md) for the I/O contract, actionable issues and examples. Also accept independent comparison-packet projections. Return VerificationSet against that projection; the caller binds it with comparison-accept. Never approve a comparison solely from its own supported cell labels.

Read [contracts.md](references/contracts.md). Run in a separate task context from the writer; use a different producer.context_id. Accept an arbitrary report plus source text, a ReviewDraft and Evidence, or a verification packet. Do not receive or rely on writer self-defense. Never search externally, complete bibliography metadata, or claim external publication/retraction verification.

For a human report, use import-artifact --kind report and explicit bibliography aliases for numbered / author-year candidate mappings. Return ambiguous_reference when more than one source fits. Preserve the original text. Extract factual statements and create Claim plus exact claim_mappings on that unchanged text; inspect every line, including headings, for undeclared facts. Do not inspect only writer-registered claims. Citation mapping does not establish source support. If source files are missing, return needs_source instead of guessing.

For native artifacts, create a packet with `verification-packet` and inspect the draft, every lines_to_scan entry, evidence and original source_context. Reopen supplied original documents if neighboring context is inadequate. Check each number with its method, dataset/population, unit, baseline and timepoint. Preserve negation, uncertainty and applicability. Reject secondary-report evidence presented as directly read original findings. Check cross-paper consensus against counterevidence and duplicate versions in the provided materials.

Return an enveloped VerificationSet. Copy target_artifact_id, target_hash and evidence_hashes from the packet. Give every delivered claim exactly one supported / partially_supported / unsupported / contradicted / uncertain verdict, with an independent reason and the exact evidence_refs assessed. supported means the whole statement is supported; partial support cannot pass without narrowing or supplementing the claim and rerunning verification.

Set scan_completed only after independently scanning every nonempty draft line. Include one scan_findings entry per lines_to_scan item with its exact start_char/end_char, classification factual or non_factual, a concrete reason, and claim_ids for factual lines. An unregistered factual statement is an issue, even if it has an inline citation. Do not classify a factual heading as non_factual just to satisfy a gate. List unresolved issues; an empty issues array is an actual attestation, not a default.

Use verification_method="independent_model_source_review" for source model review; the program generates independent_model_sharded_review only after validating component proofs and a separate AssemblyAudit. Preserve actual model/harness identifiers when known and explicitly mark manual review not performed. Locator checks must be program-validated; schema validation is not a semantic verdict. For oversized inputs ask the caller to use verification-plan; never truncate silently or assert scan_completed without full delivery.

Reopen and validate the saved VerificationSet. The program gate rejects stale report hashes, stale evidence, same writer/verifier contexts, omitted verdicts, partial support and incomplete scans. Repair suggestions must identify the claim and required correction. Do not rewrite source text or edit the writer's report in the verifier task. Return records and issues to the caller, leaving repair and resubmission to the caller.
