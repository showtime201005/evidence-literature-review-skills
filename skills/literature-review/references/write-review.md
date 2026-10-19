---
name: write-review
description: Write or revise a corpus-only literature review from supplied traceable evidence, comparisons or external research notes. Use for a complete review or one section, with explicit claim-to-source mappings, without requiring a particular analysis pipeline.
---

# Write an evidence-linked review

For native OpenCode or DeepAgents execution, read [native-harnesses.md](references/native-harnesses.md). This skill includes its own scripts/harness_runner.py; a standalone capability requires only this skill installation. Evidence handoffs include a readable claim/source catalog when source materials are supplied.


For report supplementation read [research-modes.md](references/research-modes.md). Preserve the original report, draft exact gaps and a GapResolutionSet, keep conditions with every value, and use augmentation-draft for source verification. Only filled gaps are patched; partial, incomparable, conflicting or missing data stay unresolved. The unchanged original report is not automatically verified. For full reviews use the supplied QuestionEvidenceMap to answer every question and retain counterevidence; use verification-shards.md when handing off final verification.

Read [interface.md](references/interface.md) and [data-dictionary.md](references/data-dictionary.md) for the standalone I/O contract and examples. Use handoff for paired immutable JSON and readable Markdown; preserve raw extraction fields when selecting report content. A not-selected claim is not a not-reported source finding.

Read [contracts.md](references/contracts.md). Use the bundled scripts/litreview.py. Accept external qualified evidence and notes; do not check their tool of origin. If evidence is missing, write an explicitly unverified draft and return structured needs_source / needs_extraction. Do not manufacture quotes or run external research.

Read the research question, materials, source gaps and all supplied paper analyses before choosing themes. Explain corpus boundaries and distinguish a gap in the supplied corpus from a gap in the entire field. Include scope, methods, thematic synthesis, conditions, disagreements, gaps and limitations. Do not require every source in every paragraph; only cite sources supporting that claim.

Build substantive prose as Claim records. Bind each statement to program-validated evidence IDs, preserving exact study settings and uncertainty. Save synthesis support, counterevidence and conditions as additional Claim fields. Preserve derived_from_claim_refs when reformulating supplied claims; absent lineage means not mapped, not that the source result was unused. Label analyst_inference explicitly. Do not reuse a claim ID for a changed text or evidence set. Keep an unresolved question visible when deleting an unsupported statement removes question coverage.

For a full-corpus deliverable, create a per-paper appendix section for every logical paper, including versions, contribution, findings, limitations, source gaps and relevance. Put delivered appendix findings in the same mapped ReviewDraft so the verifier checks them too. Preserve different evaluation settings in cross-paper prose. Use neutral noun headings rather than unsupported scientific claims in headings.

Write a JSON list of sections using the format in contracts.md, then run:

```bash
python /ABS/SKILL/scripts/litreview.py draft sections.json --context-id WRITER_CONTEXT --out draft.json
```

This builds exact Unicode code point mappings and citation placeholders. Retain `{{evidence:EVIDENCE_ID}}` until the program renderer assigns numbered references. Bibliography must use only supplied metadata. Never fill missing dates, authors, DOI or page numbers by inference.

Use `render` for a clearly marked draft. For a finalized single section, supply an independent VerificationSet to the Python render API; full-corpus publication uses `deliver` after appendix, matrix and coverage gates. Do not self-approve the draft. Hand off the final immutable draft and source evidence to an isolated verifier context without writer rationales. A changed draft or source/evidence requires new verification. Do not report passed before the program gate accepts the matching records.
