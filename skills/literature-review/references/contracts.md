# Portable contracts and commands

For v0.5 full research or report supplementation, read research-modes.md and verification-shards.md first. Their review-deliver / augment-deliver gates supersede the legacy full-delivery example below. Evidence arguments accept JSON and `.jsonl` emitted by assemble. Large comparisons can use comparison-draft before verification-plan; no oversized comparison-packet is needed. New research contracts use contracts-v2.schema.json; examples/research-v05 contains unverified user input examples only.

For v0.4 capabilities read data-dictionary.md and interface.md first. New PaperAnalysis / ComparisonSet / TaskResult use schema 2.0.0 with capability-check; old 1.x examples below remain valid legacy formats, not automatic v2 upgrades. Use comparison-packet / comparison-accept for independently verified comparisons. Missing extraction is not_extracted, not not_reported. Use handoff and handoff-check for human-readable, hash-bound artifacts.

Use `python /ABS/SKILL/scripts/litreview.py --help`. The wrapper includes a pinned local core and does not need pip or an API key. It works from any current directory. Public schemas are bundled at scripts/runtime/litreview_core/contracts/contracts.schema.json. Model inference is performed by your harness, never by the script.

Use envelope `{schema_version:VERSION, artifact_type:TYPE, artifact_id:UNIQUE_ID, payload:{...}, producer:{context_id:ACTUAL_CONTEXT,model:ACTUAL_OR_UNKNOWN,harness:ACTUAL_OR_UNKNOWN}}`. VERSION is 2.0.0 for new PaperAnalysis, ComparisonSet, TaskResult, FieldAssessmentSet and ComparisonVerification; existing Evidence, Claim, TaskSpec, ChunkAnalysis and ReviewDraft examples use 1.0.0. VerificationSet accepts both (v2 issues are typed). Extra optional fields are accepted. Runtime-created IDs derive from payload content; imported IDs are preserved. Provenance declarations are not cryptographic authentication.

## Reading packets

A job task is TaskSpec with request, profile, paper_id, source_hashes, metadata, source_gaps and `parts`. Each part includes part_id, block_id, document_id, content_hash, kind, section_path, start_byte, end_byte, text. Offsets are original UTF-8 bytes `[start,end)`; do not compute them as Unicode indices. Exact quotes can omit offsets unless repeated. Read all parts before claiming success.

Return this ChunkAnalysis shape (replace all placeholders with packet values):

```json
{
  "schema_version":"1.0.0", "artifact_type":"ChunkAnalysis", "artifact_id":"unique-chunk-id",
  "producer":{"context_id":"WORKER_ID","model":"unknown","harness":"unknown"},
  "payload": {
    "task_id":"TASK_ID", "source_hashes":["COPY_SOURCE_SHA256"],
    "observations":[{
      "part_id":"PART_ID", "status":"analyzed", "summary":"Concrete reading note describing this part.",
      "findings":[{
        "field":"results", "text":"The finding with its dataset, comparison and limitations.",
        "quote":"Exact supplied source quote", "source_role":"author_result"
      }]
    }]
  }
}
```

Observations must contain every part exactly once. Empty findings are valid for metadata, headings or irrelevant prose, but summary must explain the actual content. References require status reference_catalogued. Optional start_byte/end_byte must both be supplied and match exact bytes. Valid field values: research_question, contributions, method, evaluation, results, limitations, conditions, relevance, unexpected_findings. Source roles: author_result, author_limitation, secondary_report, context, analyst_inference.

Use exact full table text if citing table rows. When a finding depends on separate caption/notes, add optional findings[].spans: an array of {document_id,content_hash,start_byte,end_byte,excerpt}. Include the quoted table span plus exact caption/notes spans. All spans must fall inside parts delivered in this packet. The program will create one combined Evidence; no manual replacement is needed. If context is outside this packet, return needs_input with a context request instead of inventing it.

Core commands:

```bash
python /ABS/SKILL/scripts/litreview.py prepare PAPERS --out CORPUS
python /ABS/SKILL/scripts/litreview.py job init --corpus CORPUS --out JOB --config CONFIG.json --model-config KNOWN_MODEL_SETTINGS --max-chars 16000
python /ABS/SKILL/scripts/litreview.py job next --job JOB --worker WORKER_CONTEXT
python /ABS/SKILL/scripts/litreview.py job submit RESPONSE.json --job JOB --worker WORKER_CONTEXT
python /ABS/SKILL/scripts/litreview.py job status --job JOB
python /ABS/SKILL/scripts/litreview.py job assemble --job JOB --out ASSEMBLED
```

`job next` outputs task_path, not the full text. Read the actual file without truncation. A default lease lasts 600 seconds; make it longer for a bounded long task via --lease-seconds. After expiry, do not submit stale work; claim a fresh task. Failed submissions do not increase coverage. `job cancel`, `job retry`, `job rebuild` and `reuse` preserve receipt-based checkpoints. Use new revision jobs for changed sources/specifications; unknown model settings disable reuse.

Minimal config (also available as references/default-config.json):

```json
{"source_policy":"corpus_only","external_lookup":false,"max_papers":100,"depth":"standard","research_question":"User research question","completion_priority":"full_corpus","deadline_mode":"soft","max_workers":4,"max_repair_rounds":2}
```

Legacy PaperAnalysis v1 payload: paper_id, analysis_profile, fields (each field has status/text/claim_refs), claim_refs, coverage_refs. Its historic missing-value enum does not distinguish missing extraction. New outputs MUST use v2 and not_extracted unless an explicit absence/applicability assessment exists. Never replace missing values with zero. Field status and model reading notes are not independent semantic approval.

## Comparison and writing

Legacy ComparisonSet v1 payload (new comparisons use the complete v2 example in assets/examples):

```json
{"question":"Comparison question","dimensions":["method"],"material_refs":["claim-id"],"cells":[{"paper_id":"p1","dimension":"method","status":"supported","material_refs":["claim-id"],"verification_status":"unverified","conditions":"Study population and settings"}],"unknowns":[],"contradiction_candidates":[]}
```

Every paper/dimension needs one cell for full publication. not_addressed is checked absence, unresolved is insufficient information. Only legacy v1 cell prose is tied to report claims. For v2 retain unverified in cells and bind independent ComparisonVerification instead; see interface.md.

Claim: claim_id, text, claim_type (source_fact/synthesis/analyst_inference/scope_statement), evidence_refs (Evidence IDs), support_status (unverified initially). Add support/counterevidence/conditions as needed. Evidence is created by the source tool, not by inventing excerpt offsets. Its payload has evidence_id, spans, exact joined excerpt and source_role. Call evidence --corpus CORPUS --document DOC --quote-file EXACT_QUOTE --out FILE; repeated quotes need explicit byte offsets. Native Evidence IDs are retained in report placeholders.

Write sections.json as a JSON array:

```json
[{"heading":"Methods and scope","claims":[{"claim_id":"scope1","text":"This review analyzes only the provided texts.","claim_type":"scope_statement","evidence_refs":[],"support_status":"unverified"}]},{"heading":"Paper appendix","paper_id":"p1","claims":[{"claim_id":"finding1","text":"A precise source-supported finding.","claim_type":"source_fact","evidence_refs":["evidence-id"],"support_status":"unverified"}]}]
```

Run `draft sections.json --context-id WRITER --out draft.json`. It creates ReviewDraft text, claims, exact claim_mappings, citation_map and paper_sections. Every paper needs a nonempty appendix section in full-corpus mode. Rewrite IDs when claim text/evidence changes. Never map a paraphrase to a different text span.

## Verification

Run `verification-packet draft.json --corpus CORPUS --evidence E1.json --evidence E2.json --out packet.json`. Evidence arguments repeat. Packets include source context and all nonempty lines, not writer arguments. An oversized packet is blocked; request a sectioned review rather than silently truncating. For large corpora, use bounded reports or focused section verification plus a separately checked final assembled report.

VerificationSet example:

```json
{
 "schema_version":"1.0.0","artifact_type":"VerificationSet","artifact_id":"unique-verification",
 "producer":{"context_id":"VERIFIER_DIFFERENT_FROM_WRITER","model":"unknown","harness":"unknown"},
 "payload":{
  "target_artifact_id":"COPY_PACKET_TARGET","target_hash":"COPY_PACKET_HASH",
  "evidence_hashes":{"evidence-id":"COPY_PACKET_HASH"},
  "locator_checks":[],
  "verdicts":[{"claim_id":"finding1","status":"supported","reason":"Independent explanation of what the original source supports and its conditions.","evidence_refs":["evidence-id"]}],
  "issues":[],"scan_completed":true,
  "scan_findings":[{"start_char":0,"end_char":20,"classification":"factual","reason":"This line reports a study result and is represented by the mapped claim.","claim_ids":["finding1"]}],
  "verification_method":"independent_model_source_review"
 }
}
```

Return every claim verdict, including scope statements (which may have empty evidence_refs if procedure, not scientific evidence). Return one scan finding per packet lines_to_scan item, including headings; non_factual lines still need reasons. Report missing facts and ambiguities as issues. Never auto-fill supported from the writer's label.

Use `deliver --job JOB --draft DRAFT --verification VERIFICATION --comparison COMPARISON --evidence EVIDENCE ... --out DELIVERY`. It checks complete source coverage, matching report/evidence hashes, distinct contexts, complete scan, all supported verdicts, matrix and per-paper appendices. No failed/partial claim may be averaged away. Outputs explicitly state automatic model verification and manual-review status.

## External inputs

Use import-artifact --kind native/report/notes/csv/bibliography. CSV needs source_id. Bibliography is a JSON array of `{label,source_ref,aliases?}`; author-year aliases are explicit exact tokens. Mappings are candidates, not evidence. Imported "verified" flags do not become trusted. Preserve arbitrary original report text when constructing its claim mappings; missing citations and unmapped factual text are verifier issues.

## Completion and trust

Separate execution complete/partial/blocked from quality passed/needs_revision/unverified. A successful model task or schema check is not scientific support. Locator checks prove only exact text location. Full coverage proves delivered observations exist, not perfect comprehension. Model verification is an auditable attestation, not a human guarantee. A final report must state source gaps and missing metadata; bibliography/retraction claims remain unverified externally.
