"""Compile actual mapped artifacts into pending bounded review-proof tasks.

No model calls, identities, semantic approvals or fake passed nodes are made.
The compiler replays the public source/reader/draft validators, renders every
published section itself, and derives inventories from those actual objects.
Original UTF-8 bytes stay at source leaves; synthesis must name real, earlier
scientific premises and inherit their source references and population.
"""
from __future__ import annotations

from hashlib import sha256
import json
from typing import Any, Callable
from urllib.parse import quote

from .hierarchical_proof import (DIMENSIONS, payload_hash, seal_plan,
                                dependency_view_material, dependency_view_material_id,
                                DEPENDENCY_RECEIPT_SCHEMA, dependency_receipt)
from .review_artifacts import draft_packet, inference_packet, render_section, validate_draft
from .scientific_records import validate_reader
from .task_store import canonical
from .proof_citation_view import attach_citation_view
from .proof_submission_wire import alias_proof_packet


class PlanningError(ValueError):
    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code, self.details = code, details

    def as_dict(self):
        return {"code": self.code, "message": str(self), "details": self.details}


def _fail(code, message, details=None):
    raise PlanningError(code, message, details)


def _unique(values, label, *, nonempty=True):
    if not isinstance(values, list) or (nonempty and not values):
        _fail("INVALID_INVENTORY", label + " requires a nonempty list")
    if any(not isinstance(v, str) or not v.strip() or v != v.strip() for v in values):
        _fail("INVALID_INVENTORY", label + " contains an invalid ID")
    if len(values) != len(set(values)):
        _fail("DUPLICATE_INVENTORY", label + " contains duplicate IDs")
    return values


def _empty():
    return {dim: [] for dim in DIMENSIONS}


def _name(kind, *parts):
    return kind + "/" + "/".join(quote(part, safe="") for part in parts)


def _originals(packets):
    if not isinstance(packets, list) or not packets:
        _fail("NO_SOURCES", "Original source packets are required")
    by_paper, raw, units, questions = {}, {}, {}, None
    for packet in packets:
        if not isinstance(packet, dict) or packet.get("schema") != "scientific-source/1":
            _fail("INVALID_SOURCE_PACKET", "Expected scientific-source/1 packets")
        pid = packet.get("paper_id")
        _unique([pid], "paper ID")
        if "/" in pid or any(ord(c) < 32 for c in pid) or pid in by_paper:
            _fail("DUPLICATE_OR_INVALID_PAPER", "Original papers need unique canonical IDs", pid)
        if not isinstance(packet.get("parts"), list) or not packet["parts"]:
            _fail("MISSING_SOURCE_PART", "Every source needs its actual original parts", pid)
        content, seen = bytearray(), set()
        for part in packet["parts"]:
            part_id = part.get("part_id")
            _unique([part_id], "source part ID")
            if part_id in seen or not isinstance(part.get("text"), str):
                _fail("INVALID_SOURCE_PART", "Missing/duplicate source part", pid)
            seen.add(part_id)
            encoded = part["text"].encode("utf-8")
            if (type(part.get("start_byte")) is not int or type(part.get("end_byte")) is not int
                    or part["start_byte"] != len(content) or part["end_byte"] != len(content) + len(encoded)):
                _fail("SOURCE_OFFSET_MISMATCH", "Source parts are not contiguous original UTF-8 bytes", pid)
            content.extend(encoded)
            key = pid + "/" + part_id
            units[key] = {"paper_id": pid, "part_id": part_id, "start_byte": part["start_byte"],
                          "end_byte": part["end_byte"], "text": part["text"],
                          "source_sha256": packet["source_sha256"], "text_sha256": sha256(encoded).hexdigest()}
        if not bytes(content).strip() or sha256(content).hexdigest() != packet.get("source_sha256"):
            _fail("SOURCE_HASH_MISMATCH", "Original bytes differ from their declared snapshot", pid)
        q = packet.get("questions")
        if not isinstance(q, list):
            _fail("INVALID_QUESTIONS", "Original request questions are missing")
        qids = _unique([item.get("id", item.get("question_id")) for item in q], "request questions")
        if any(not isinstance(item.get("text"), str) or not item["text"].strip() for item in q):
            _fail("INVALID_QUESTIONS", "Question text is missing")
        qmap = {qid: {**item, "id": qid} for qid, item in zip(qids, q)}
        if questions is not None and canonical(qmap) != canonical(questions):
            _fail("QUESTION_CONTEXT_MISMATCH", "All papers must bind the same original research request")
        questions = qmap
        by_paper[pid], raw[pid] = packet, bytes(content)
    return by_paper, raw, units, questions


def _reader_records(records, packets):
    if not isinstance(records, list):
        _fail("INVALID_RECORDS", "Original reader records are required")
    out = {}
    for record in records:
        pid = record.get("paper_id")
        if pid in out or pid not in packets:
            _fail("DUPLICATE_OR_UNKNOWN_RECORD", "Record is duplicated or outside the original corpus", pid)
        packet = packets[pid]
        if record.get("source_sha256") != packet["source_sha256"]:
            _fail("STALE_READER_RECORD", "Reader record names another original version", pid)
        try:
            evidence = {e["id"]: e for e in record["evidence"]}
            if len(evidence) != len(record["evidence"]):
                raise ValueError("Duplicate reader Evidence IDs")
            parts = {p["part_id"]: p for p in packet["parts"]}
            findings = []
            for finding in record["findings"]:
                quotes = []
                for eid in finding["evidence_refs"]:
                    item = evidence[eid]
                    part = parts[item["part_id"]]
                    local = item["start_byte"] - part["start_byte"]
                    block = part["text"].encode("utf-8")
                    start = len(block[:local].decode("utf-8"))
                    if local < 0 or item["end_byte"] > part["end_byte"]:
                        raise ValueError("Reader evidence escapes its original part")
                    quotes.append({"part_id": item["part_id"], "quote": item["quote"], "start_char": start})
                findings.append({key: finding[key] for key in ("local_id", "field", "text", "attribution", "obligations")}
                                | {"evidence": quotes})
            original_submission = {"observations": record["observations"], "findings": findings,
                                   "fields": record["fields"], "questions": record["questions"]}
            rebuilt = validate_reader(packet, original_submission, execution_id=record["execution_id"])
            if canonical(rebuilt) != canonical(record):
                raise ValueError("Record differs from native source-bound reconstruction")
        except (KeyError, TypeError, ValueError, UnicodeError) as exc:
            _fail("READER_RECORD_MISMATCH", "Reader coverage/evidence/obligations cannot be reconstructed", {"paper_id": pid, "reason": str(exc)})
        out[pid] = record
    if set(out) != set(packets):
        _fail("MISSING_READER_RECORD", "Every provided paper requires its actual complete reader record", sorted(set(packets) - set(out)))
    return out


def _validated_sections(sections, packets, records, questions):
    if not isinstance(sections, list) or not sections:
        _fail("NO_SECTIONS", "Actual mapped sections are required")
    ids = _unique([s.get("section_id") for s in sections], "section IDs")
    validated, renders = {}, {}
    for section in sections:
        sid = section["section_id"]
        papers = _unique(section.get("paper_ids"), "section paper membership")
        if not set(papers) <= set(packets):
            _fail("UNKNOWN_SECTION_PAPER", "Section names an unprovided paper", sid)
        qids = _unique(section.get("question_ids"), "section question membership")
        if not set(qids) <= set(questions):
            _fail("UNKNOWN_SECTION_QUESTION", "Section names an unknown research question", sid)
        premises = _unique(section.get("premise_section_ids"), "premise sections", nonempty=False)
        if sid in premises:
            _fail("SELF_PREMISE", "A section cannot certify itself as its own premise", sid)
        if not set(premises) <= set(validated):
            _fail("UNKNOWN_OR_FORWARD_PREMISE", "Scientific premises must be actual earlier sections", sid)
        if section.get("kind") == "synthesis" and not premises:
            _fail("MISSING_SYNTHESIS_PREMISE", "Synthesis cannot bypass original-source premise verification", sid)
        if section.get("kind") == "paper_card" and premises:
            _fail("INVALID_CARD_PREMISE", "Paper cards are direct original-source leaves", sid)
        selected_packets = [packets[p] for p in papers]
        selected_records = [records[p] for p in papers]
        # validate_draft stores question IDs in sorted order; the original
        # writer packet retains research-question order, which is hash-bound.
        selected_questions = [question for qid, question in questions.items() if qid in set(qids)]
        prior = [validated[p] for p in premises]
        try:
            full = draft_packet(section["kind"], selected_packets, selected_records, selected_questions,
                                dimensions=section["dimensions"], premises=prior)
            candidates = [full]
            if section["kind"] == "synthesis" or (section["kind"] == "comparison" and prior):
                candidates.insert(0, inference_packet(prior, selected_packets, selected_records, selected_questions,
                    kind=section["kind"], dimensions=section["dimensions"]))
            packet = next((p for p in candidates if sha256(canonical(p)).hexdigest() == section.get("packet_sha256")), None)
            if packet is None:
                raise ValueError("Writer input packet hash/context/obligations changed")
            value = {key: section[key] for key in ("claims", "retention", "cells")}
            rebuilt = validate_draft(packet, value, execution_id=section["writer_execution_id"])
            if canonical(rebuilt) != canonical(section):
                raise ValueError("Section hash, claims, source versions, or declared context changed")
            # A source-backed inference cannot silently enlarge its certified population.
            premise_claims = {p["section_id"] + "/" + c["local_id"]: c for p in prior for c in p["claims"]}
            for claim in section["claims"]:
                if section["kind"] in ("comparison", "synthesis") and prior:
                    population = {p for cid in claim["premise_claim_ids"] for p in premise_claims[cid]["population_paper_ids"]}
                    if not set(claim["population_paper_ids"]) <= population:
                        raise ValueError("Claim population is outside its certified premises")
            rendered = render_section(section)
            actual_lines = [(start, line) for start, line in _nonempty_lines(rendered["text"])]
            if [(x["start_char"], x["text"]) for x in rendered["lines"]] != actual_lines:
                raise ValueError("Native rendered nonempty-line inventory differs from actual text")
        except (KeyError, TypeError, ValueError, AssertionError) as exc:
            _fail("SECTION_RECONSTRUCTION_MISMATCH", "Actual section cannot be reconstructed from its original inputs", {"section_id": sid, "reason": str(exc)})
        validated[sid], renders[sid] = section, rendered
    cards = [s["paper_ids"][0] for s in sections if s["kind"] == "paper_card"]
    if len(cards) != len(set(cards)) or set(cards) != set(packets):
        _fail("MISSING_OR_DUPLICATE_PAPER_CARD", "Every provided paper needs exactly one final paper card", sorted(set(packets) - set(cards)))
    return ids, validated, renders


def _nonempty_lines(text):
    offset = 0
    for line in text.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        if body.strip():
            yield offset, body
        offset += len(line)


def node_payload(bundle, node_id, dependency_nodes=None, *, dependency_receipts=None):
    """Actual research input payload; runtime adds real child proofs and skills.

    Raw bytes are decoded as UTF-8 only for delivery, preserving source bytes
    on re-encoding.  Parent identities must attest the original material hashes.
    """
    spec = bundle["node_specs"][node_id]
    dependencies = dependency_nodes or {}
    if dependencies and set(dependencies) != set(spec["dependencies"]):
        _fail("DEPENDENCY_SET_MISMATCH", "Deliver every and only the planned child proof")
    result = {"schema": "hierarchical-proof-task/1", "node_id": node_id, "kind": spec["kind"],
            "review_mode": spec.get('review_mode', 'assigned_units'),
            "coverage": spec["coverage"], "material_hashes": spec["inputs"],
            "materials": {mid: (bundle["materials"][mid].decode("utf-8") if isinstance(bundle["materials"][mid], bytes)
                                 else bundle["materials"][mid]) for mid in spec["inputs"]},
            "required_dependency_ids": spec["dependencies"]}
    compact = (bundle.get('dependency_delivery') == DEPENDENCY_RECEIPT_SCHEMA or
               node_id in bundle.get('plan', {}).get('payload', {}).get('dependency_delivery', {}).get('node_ids', []))
    if compact:
        receipts = dependency_receipts or {}
        if dependencies and dependency_receipts is None:
            _fail('DEPENDENCY_PREFLIGHT_REQUIRED', 'Compact delivery requires host-preflighted child receipts')
        if receipts and (set(receipts) != set(dependencies) or any(
                receipts[dep] != dependency_receipt(dependencies[dep]) for dep in receipts)):
            _fail('DEPENDENCY_RECEIPT_MISMATCH', 'Deliver exact receipts for every actual child proof')
        result.update(dependency_delivery=DEPENDENCY_RECEIPT_SCHEMA, dependency_receipts=receipts)
    else:
        if dependency_receipts:
            _fail('UNDECLARED_DEPENDENCY_RECEIPT', 'Legacy tasks require complete child proof JSON')
        result['dependency_proofs'] = dependencies
    return result


def dependency_size_reservations(bundle, node_id):
    """Explicit pending sizing structures, never fabricated attestations."""
    spec, specs = bundle['node_specs'][node_id], bundle['node_specs']
    compact = bundle.get('dependency_delivery') == DEPENDENCY_RECEIPT_SCHEMA
    if compact:
        return [{'schema': 'dependency-proof-receipt/PENDING-SIZE-RESERVATION', 'node_id': dep,
            'kind': specs[dep]['kind'], 'status': 'pending_not_an_attestation',
            'coverage': specs[dep]['coverage'],
            'proof_payload_hash_size_placeholder': sha256(('pending-sizing-only:' + dep).encode()).hexdigest(),
            'not_an_attestation': 'Complete reason/issues are reserved separately; no semantic verdict exists.'}
            for dep in spec['dependencies']]
    return [{'node_id': dep, 'inputs': specs[dep]['inputs'], 'coverage': specs[dep]['coverage'],
             'dependencies': {d: 'f' * 64 for d in specs[dep]['dependencies']},
             'not_an_attestation': 'Structural reservation only; no semantic verdict has been created.'}
            for dep in spec['dependencies']]


def plan_review(sections, packets, records, *, root_section_ids=None,
                token_counter: Callable[[str], int] | None = None,
                max_input_tokens: int = 120000, max_input_bytes: int = 800000,
                max_scientific_units: int = 16, compact_dependencies: bool = True,
                merge_full_source: bool = False):
    """Compile a versioned plan, material store and *pending* real-model tasks.

    ``token_counter`` counts the canonical task JSON string (not provider usage).
    Diagnostics include a 2KB reason allowance per child proof.  Runtime still
    MUST admit the actual complete messages/tools/history/output before HTTP.
    No source is truncated to satisfy these bounds; oversized nodes fail with
    actionable diagnostics for additional model-directed grouping/splitting.
    """
    if type(max_input_tokens) is not int or not 1 <= max_input_tokens <= 180000 or type(max_input_bytes) is not int or max_input_bytes < 1:
        _fail("INVALID_BUDGET", "Supply positive bounded input budgets (tokens <=180000)")
    if type(max_scientific_units) is not int or not 1 <= max_scientific_units <= 128:
        _fail('INVALID_BUDGET', 'max_scientific_units must be an integer from 1 to 128; default 16, use 8 for finer source/output granularity; context/output admission remains mandatory')
    if type(compact_dependencies) is not bool:
        _fail('INVALID_DEPENDENCY_DELIVERY', 'compact_dependencies must be an explicit boolean')
    if type(merge_full_source) is not bool:
        _fail('INVALID_PACKING_OPTION', 'merge_full_source must be an explicit boolean; default False')
    packet_map, raw, units, questions = _originals(packets)
    record_map = _reader_records(records, packet_map)
    ordered, section_map, renders = _validated_sections(sections, packet_map, record_map, questions)
    if root_section_ids is None:
        referenced = {p for s in sections for p in s["premise_section_ids"]}
        terminal = [sid for sid in ordered if sid not in referenced]
        root_section_ids = [sid for sid in terminal if section_map[sid]["kind"] == "synthesis"] or terminal
    roots = _unique(root_section_ids, "final root sections")
    if not set(roots) <= set(section_map):
        _fail("UNKNOWN_ROOT_SECTION", "Final report root is not an actual section")
    root_papers = {p for sid in roots for p in section_map[sid]["paper_ids"]}
    root_questions = {q for sid in roots for q in section_map[sid]["question_ids"]}
    if root_papers != set(packet_map) or root_questions != set(questions):
        _fail("INCOMPLETE_ROOT_SCOPE", "Final report roots omit provided papers or research questions",
              {"missing_papers": sorted(set(packet_map) - root_papers), "missing_questions": sorted(set(questions) - root_questions)})

    materials, bindings, requirements, expected, specs = {}, _empty(), _empty(), _empty(), {}
    bindings = {dim: {} for dim in DIMENSIONS}
    requirements = {dim: {} for dim in DIMENSIONS}
    source_ids = {pid: _name("original", pid) for pid in packet_map}
    for pid, data in raw.items():
        materials[source_ids[pid]] = data
        materials[_name("reader", pid)] = record_map[pid]
    all_claims = {cid: c for rendered in renders.values() for cid, c in rendered["claims"].items()}
    section_cov, base_inputs, section_contexts = {}, {}, {}
    reader_obligations = {o['id']: (record, next(f for f in record['findings'] if f['local_id'] == o['finding_id']))
                          for record in records for o in record['obligations']}
    global_text, global_lines, offset = [], [], 0
    for sid in ordered:
        section, rendered = section_map[sid], renders[sid]
        cov, mids = _empty(), set()
        section_mid, render_mid, context_mid = _name("section", sid), _name("render", sid), _name("context", sid)
        materials[section_mid], materials[render_mid] = section, rendered
        materials[context_mid] = {"schema": "proof-section-context/1", "section_id": sid, "kind": section['kind'], "paper_ids": section["paper_ids"],
            "source_versions": section["source_versions"], "questions": [questions[q] for q in section["question_ids"]],
            "dimensions": section["dimensions"], "premise_section_ids": section["premise_section_ids"],
            "section_sha256": payload_hash(section), "render_text_sha256": rendered['text_sha256'],
            "actual_heading": rendered['lines'][0]['text'],
            "assigned_review": "Independently check assigned actual units; partial coverage is not a whole-section approval."}
        section_contexts[sid] = context_mid
        mids.update((section_mid, render_mid, context_mid))
        for cid, claim in rendered["claims"].items():
            mid = _name("claim", cid)
            materials[mid] = {"claim_id": cid, **claim}
            cov["claims"].append(cid)
            bindings["claims"][cid] = [mid, context_mid]
            requirements["claims"][cid] = sorted({source_ids[units[ref]["paper_id"]] for ref in claim["evidence_refs"]})
            mids.add(mid)
        for line in rendered["lines"]:
            lid, mid = line["id"], _name("line", line["id"])
            materials[mid] = line
            cov["lines"].append(lid)
            bindings["lines"][lid] = [mid, context_mid]
            requirements["lines"][lid] = sorted({source_ids[units[ref]["paper_id"]] for cid in line["claim_ids"] for ref in all_claims[cid]["evidence_refs"]})
            mids.add(mid)
            global_lines.append({**line, "section_id": sid, "start_char": offset + line["start_char"], "end_char": offset + line["end_char"]})
        for pid in section["paper_ids"]:
            unit = _name(sid + "/paper", pid)
            materials[unit] = {"section_id": sid, "paper_id": pid, "source_sha256": packet_map[pid]["source_sha256"]}
            cov["papers"].append(unit)
            bindings["papers"][unit], requirements["papers"][unit] = [unit], [source_ids[pid]]
            mids.add(unit)
        for qid in section["question_ids"]:
            unit = _name(sid + "/question", qid)
            claim_ids = [cid for cid, c in rendered["claims"].items() if qid in c["question_ids"]]
            materials[unit] = {"section_id": sid, "question": questions[qid], "claim_ids": claim_ids}
            cov["questions"].append(unit)
            bindings["questions"][unit] = [unit]
            # This inventory unit binds the original question and exact answer
            # IDs. Scientific answers themselves have separate source duties.
            requirements["questions"][unit] = []
            mids.add(unit)
        for cell in section["cells"]:
            unit = _name(sid + "/cell", cell["paper_id"], cell["dimension"])
            materials[unit] = {"section_id": sid, **cell, "global_claim_ids": [sid + "/" + c for c in cell["claim_ids"]]}
            cov["cells"].append(unit)
            bindings["cells"][unit], requirements["cells"][unit] = [unit, context_mid], [source_ids[cell["paper_id"]]]
            mids.add(unit)
        dispositions = {item["obligation_id"]: item for item in section["retention"]}
        for obligation in section["obligations"]:
            unit = _name(sid + "/obligation", obligation["id"])
            materials[unit] = {"section_id": sid, "definition": obligation, "disposition": dispositions[obligation["id"]]}
            if obligation['id'] in reader_obligations:
                original_record, finding = reader_obligations[obligation['id']]
                materials[unit]['original_finding'] = finding
                materials[unit]['original_question_dispositions'] = [q for q in original_record['questions']
                    if finding['local_id'] in q['support'] + q['counterevidence']]
            cov["obligations"].append(unit)
            bindings["obligations"][unit] = [unit, context_mid]
            requirements["obligations"][unit] = sorted({source_ids[units[ref]["paper_id"]] for ref in obligation["source_refs"]})
            mids.add(unit)
        if section['kind'] == 'paper_card':
            pid = section['paper_ids'][0]
            unit = _name(sid + '/obligation', 'full_source_review/' + pid)
            materials[unit] = {'section_id': sid, 'definition': {
                'id': 'full_source_review/' + pid, 'kind': 'full_source_review',
                'paper_id': pid, 'source_sha256': packet_map[pid]['source_sha256'],
                'part_ids': [p['part_id'] for p in packet_map[pid]['parts']],
                'reader_sha256': payload_hash(record_map[pid]), 'card_sha256': payload_hash(section),
                'claim_ids': list(rendered['claims']),
                'source_review_requirement': 'Read the complete original paper and complete reader record; compare all actual card claims and dispositions for important scientific omissions. Local citation support is insufficient.',
                'assembly_review_requirement': 'Independently inspect the complete card and reader record against the complete-source proof, original version and all original reading parts. Check omissions and integration; do not assume citation support proves completeness.'},
                'disposition': None}
            cov['obligations'].append(unit)
            bindings['obligations'][unit] = [unit, context_mid]
            requirements['obligations'][unit] = [source_ids[pid]]
            mids.add(unit)
        section_cov[sid], base_inputs[sid] = cov, mids
        for dim in DIMENSIONS:
            expected[dim].extend(cov[dim])
        global_text.append(rendered["text"] + "\n\n")
        offset += len(rendered["text"]) + 2

    text = "".join(global_text)
    if [(line["start_char"], line["text"]) for line in global_lines] != list(_nonempty_lines(text)):
        _fail("GLOBAL_LINE_MAPPING_MISMATCH", "Final concatenation has untracked nonempty lines")
    materials["delivery/render"] = {"schema": "mapped-review-render/1", "text": text, "lines": global_lines}
    scope_id = "review/scope"
    materials[scope_id] = {"schema": "review-scope/1", "paper_ids": sorted(packet_map),
        "source_versions": {p: packet_map[p]["source_sha256"] for p in sorted(packet_map)},
        "questions": questions, "root_section_ids": roots, "section_ids": ordered,
        "section_hashes": {s: payload_hash(section_map[s]) for s in ordered},
        "delivery_sha256": payload_hash(materials["delivery/render"]),
        "coverage_counts": {dim: len(expected[dim]) for dim in DIMENSIONS}}
    # A source shard owns actual science units, never a fabricated approval of
    # a subset of an already-wide child. Parent source shards still receive
    # EVERY science material covered by each real direct child they depend on.
    source_owners, source_closures, section_assembly = {}, {}, {}

    def spec_value(nid, kind, sid, coverage, input_ids, dependencies, review_mode):
        return {'node_id': nid, 'kind': kind, 'role': 'verifier' if kind in ('source', 'cross_group') else 'assembly-auditor',
                'section_id': sid, 'coverage': coverage, 'dependencies': sorted(set(dependencies)),
                'input_ids': sorted(set(input_ids)), 'inputs': {mid: payload_hash(materials[mid]) for mid in sorted(set(input_ids))},
                'state': 'pending', 'review_mode': review_mode}

    def measure(spec, extra_specs=None):
        available = {**specs, **(extra_specs or {})}
        temporary = {'materials': materials, 'node_specs': {**available, spec['node_id']: spec},
                     'dependency_delivery': DEPENDENCY_RECEIPT_SCHEMA if compact_dependencies else None}
        payload = node_payload(temporary, spec['node_id'])
        payload['dependency_size_reservations'] = dependency_size_reservations(temporary, spec['node_id'])
        # Match current deterministic worker presentation before measuring:
        # exact local citation view plus lossless responsibility aliases.
        # Full system/skills/tools/history remain the wire governor's duty.
        payload, _ = alias_proof_packet(attach_citation_view(payload))
        encoded = canonical(payload)
        measured = token_counter(encoded.decode('utf-8')) if token_counter else len(encoded)
        if type(measured) is not int or measured < 0:
            _fail('INVALID_TOKEN_COUNTER', 'Counter must return a nonnegative integer')
        # Repeated "x" is highly compressible by BPE and is NOT a safe estimate
        # of future free-text reasons. Reserve full UTF-8 bytes as tokens.
        reserve = 3072 * len(spec['dependencies'])
        return {'input_json_bytes': len(encoded) + reserve, 'input_tokens': measured + reserve,
                'counting_method': 'caller_local_tokenizer_not_wire_usage' if token_counter else 'conservative_utf8_byte_upper_bound_not_actual_tokens',
                'dynamic_child_reason_reserve_bytes': 2048, 'dynamic_child_envelope_reserve_bytes': 1024,
                'deterministic_worker_views': ['proof-citation-view', 'proof-unit-aliases/1'],
                'complete_runtime_wire_admission_required': True}

    def bounded(spec, extra_specs=None):
        spec['budget'] = measure(spec, extra_specs)
        return spec['budget']['input_tokens'] <= max_input_tokens and spec['budget']['input_json_bytes'] <= max_input_bytes

    def reject_atomic(spec):
        _fail('OVERSIZED_PROOF_NODE', 'Minimum safe scientific package exceeds the budget. Split the writing claim/section or design full-coverage source segments plus integration; never truncate sources, premises or counterevidence.',
              {'max_input_tokens': max_input_tokens, 'max_input_bytes': max_input_bytes,
               'split_writing_required': True, 'minimum_atomic_package': True,
               'nodes': [{'node_id': spec['node_id'], 'kind': spec['kind'], 'coverage': spec['coverage'], **spec['budget']}]})

    def pack(items, build, paired=None):
        # Bound downstream actual-premise fan-in and typed output, even when a
        # wide source package would fit its own context. Scientific units are
        # actual claims/obligations/cells; each requires independent assessment.
        # Full-source omission review has one explicit responsibility, with all
        # complete source/card inputs, rather than relisting every claim duty.
        full = next((index for index, atom in enumerate(items) if atom['full_source']), None)
        if full is not None and len(items) > 1:
            # Opt-in only: the original omission duty and every assigned unit
            # remain intact in one real source review. Admit only when BOTH
            # this source and its independent assembly package fit the same
            # existing budgets. A failed merge uses the original partition.
            if merge_full_source and len(items) <= max_scientific_units:
                candidate = build(items, '__merged_sizing')
                if bounded(candidate):
                    partner = paired(candidate, items) if paired else None
                    if partner is None or bounded(partner, {candidate['node_id']: candidate}):
                        return [items]
            groups = []
            if full:
                groups.extend(pack(items[:full], build, paired))
            groups.extend(pack([items[full]], build, paired))
            if full + 1 < len(items):
                groups.extend(pack(items[full + 1:], build, paired))
            return groups
        if len(items) > max_scientific_units:
            groups = []
            for start in range(0, len(items), max_scientific_units):
                groups.extend(pack(items[start:start + max_scientific_units], build, paired))
            return groups
        candidate = build(items, '__sizing')
        fits = bounded(candidate)
        partner = paired(candidate, items) if paired and fits else None
        if fits and (partner is None or bounded(partner, {candidate['node_id']: candidate})):
            return [items]
        if len(items) == 1:
            reject_atomic(partner if partner is not None else candidate)
            return [items]  # Diagnostic-only callers may collect the rejection.
        middle = len(items) // 2
        return pack(items[:middle], build, paired) + pack(items[middle:], build, paired)

    def merged_coverage(atoms):
        cov = _empty()
        for atom in atoms:
            for dim in DIMENSIONS:
                cov[dim].extend(atom['coverage'][dim])
        return cov

    for sid in ordered:
        section, cov = section_map[sid], section_cov[sid]
        is_synth = section['kind'] in ('comparison', 'synthesis') and bool(section['premise_section_ids'])
        context_id = section_contexts[sid]
        atoms, claim_atoms = [], {}

        def atom_for(dim, unit):
            atom = {'coverage': _empty(), 'inputs': set(bindings[dim][unit]),
                    'target_claims': set(), 'premise_claims': set(), 'full_source': False}
            atom['coverage'][dim].append(unit)
            atoms.append(atom)
            return atom

        for cid in cov['claims']:
            atom = atom_for('claims', cid)
            atom['target_claims'].add(cid)
            claim_atoms[cid] = atom
        for unit in cov['obligations']:
            atom = atom_for('obligations', unit)
            item = materials[unit]
            if item['definition']['kind'] == 'full_source_review':
                atom['full_source'] = True
                atom['target_claims'].update(cov['claims'])
                atom['inputs'].add(_name('section', sid))
            else:
                disposition = item['disposition']
                atom['target_claims'].update(sid + '/' + cid for cid in disposition['claim_ids'])
                if disposition['status'] == 'excluded':
                    # Exclusion is assessed against the actual candidate text,
                    # never against the writer's reason or a partial preview.
                    atom['target_claims'].update(cov['claims'])
                premise = item['definition'].get('premise_claim_id')
                if premise:
                    atom['premise_claims'].add(premise)
        for unit in cov['cells']:
            atom = atom_for('cells', unit)
            atom['target_claims'].update(materials[unit]['global_claim_ids'])
        for unit in cov['lines']:
            line = materials[_name('line', unit)]
            atom = claim_atoms[line['claim_ids'][0]] if line['claim_ids'] else atoms[0]
            atom['coverage']['lines'].append(unit)
            atom['inputs'].update(bindings['lines'][unit])
        for unit in cov['papers']:
            pid = materials[unit]['paper_id']
            atom = next(a for cid, a in claim_atoms.items() if pid in all_claims[cid]['population_paper_ids'])
            atom['coverage']['papers'].append(unit)
            atom['inputs'].update(bindings['papers'][unit])
        for unit in cov['questions']:
            candidates = materials[unit]['claim_ids']
            atom = claim_atoms[candidates[0]]
            atom['coverage']['questions'].append(unit)
            atom['inputs'].update(bindings['questions'][unit])
        for atom in atoms:
            for cid in atom['target_claims']:
                atom['inputs'].update(bindings['claims'][cid])
                atom['premise_claims'].update(all_claims[cid]['premise_claim_ids'])
            if is_synth and not atom['premise_claims']:
                # Legacy synthesis obligations may lack explicit premise IDs.
                # Full actual premises are required instead of guessing which
                # counterevidence is scientifically irrelevant.
                atom['premise_claims'].update(cid for prior in section['premise_section_ids']
                                              for cid in section_cov[prior]['claims'])

        def build_source(group, suffix):
            coverage = merged_coverage(group)
            inputs, dependencies, required = {context_id}, set(), set()
            selected_premises = set()
            selected_view = is_synth and all(all_claims[cid]['premise_claim_ids']
                for atom in group for cid in atom['target_claims'])
            for atom in group:
                inputs.update(atom['inputs'])
                for dim in DIMENSIONS:
                    for unit in atom['coverage'][dim]:
                        required.update(requirements[dim][unit])
                if is_synth:
                    for cid in atom['premise_claims']:
                        if cid not in source_owners:
                            _fail('MISSING_PREMISE_SOURCE', 'Actual premise claim has no prior independent source shard', cid)
                        dependencies.add(source_owners[cid])
                        selected_premises.add(cid)
            if is_synth:
                available = (set().union(*(set(requirements['claims'][cid]) for cid in selected_premises))
                             if selected_view and selected_premises else
                             set().union(*(source_closures[dep] for dep in dependencies)) if dependencies else set())
                if not required <= available:
                    _fail('MISSING_PREMISE_SOURCE', 'Selected actual premises do not certify all required original sources', sorted(required - available))
                if selected_view:
                    for cid in selected_premises:
                        inputs.update(bindings['claims'][cid])
                else:
                    for dep in dependencies:
                        for dim in ('claims', 'cells', 'obligations'):
                            for unit in specs[dep]['coverage'][dim]:
                                inputs.update(bindings[dim][unit])
            else:
                inputs.update(required)
                pids = [pid for pid, mid in source_ids.items() if mid in required]
                inputs.update(_name('reader', pid) for pid in pids)
                refs = {ref for atom in group for cid in atom['target_claims'] for ref in all_claims[cid]['evidence_refs']}
                refs.update(ref for atom in group for unit in atom['coverage']['obligations']
                            for ref in materials[unit]['definition'].get('source_refs', []))
                if any(atom['full_source'] for atom in group):
                    refs.update(ref for ref, value in units.items() if value['paper_id'] in pids)
                for ref in refs:
                    locator = _name('locator', ref)
                    materials[locator] = {key: value for key, value in units[ref].items() if key != 'text'}
                    inputs.add(locator)
            nid = 'src_' + sid + suffix
            view = None
            if selected_view:
                view = {dep: sorted(cid for cid in selected_premises if source_owners[cid] == dep)
                        for dep in sorted(dependencies)}
                mid = dependency_view_material_id(nid)
                materials[mid] = dependency_view_material(nid, view)
                inputs.add(mid)
            spec = spec_value(nid, 'cross_group' if is_synth else 'source', sid,
                coverage, inputs, dependencies,
                'complete_original_omission_review_and_assigned_units' if any(a['full_source'] for a in group) else 'assigned_scientific_units')
            if view is not None:
                spec['scientific_view'] = view
            return spec

        def build_assembly(source_spec, group, suffix):
            inputs = set(source_spec['inputs']) - set(source_ids.values())
            if not any(atom['full_source'] for atom in group):
                inputs.difference_update(_name('reader', pid) for pid in packet_map)
            dependencies = [source_spec['node_id']] + [section_assembly[prior] for prior in section['premise_section_ids']]
            return spec_value('asm_' + sid + suffix, 'assembly', sid, merged_coverage(group), inputs, dependencies,
                'independent_complete_card_integration' if any(a['full_source'] for a in group) else 'assigned_assembly_units')

        groups = pack(atoms, build_source, lambda source, group: build_assembly(source, group, '__paired_sizing'))
        sources = []
        for index, group in enumerate(groups):
            suffix = '' if index == 0 else '__' + str(index + 1).zfill(4)
            spec = build_source(group, suffix)
            if not bounded(spec):
                reject_atomic(spec)
            nid = spec['node_id']
            specs[nid] = spec
            delivered = set(spec['inputs']) & set(source_ids.values())
            if 'scientific_view' in spec:
                source_closures[nid] = delivered | set().union(*(set(requirements['claims'][cid])
                    for claims in spec['scientific_view'].values() for cid in claims))
            else:
                source_closures[nid] = delivered | set().union(*(source_closures[dep] for dep in spec['dependencies'])) if spec['dependencies'] else delivered
            for cid in spec['coverage']['claims']:
                source_owners[cid] = nid
            sources.append((nid, group))

        assembly_fragments = []
        for index, (source_id, group) in enumerate(sources):
            suffix = '' if index == 0 else '__' + str(index + 1).zfill(4)
            spec = build_assembly(specs[source_id], group, suffix)
            if not bounded(spec):
                reject_atomic(spec)
            specs[spec['node_id']] = spec
            assembly_fragments.append(spec['node_id'])
        if len(assembly_fragments) == 1:
            section_assembly[sid] = assembly_fragments[0]
        else:
            inputs = {context_id}
            for dim in ('claims', 'lines'):
                for unit in cov[dim]:
                    inputs.update(bindings[dim][unit])
            level = 0
            frontier = assembly_fragments
            while len(frontier) > 1:
                following = []
                offset = 0
                while offset < len(frontier):
                    width = min(4, len(frontier) - offset)
                    if width == 1:
                        following.append(frontier[offset])
                        offset += 1
                        continue
                    while True:
                        spec = spec_value('join_' + sid + '__' + str(level) + '_' + str(offset), 'assembly', sid, _empty(), inputs,
                            frontier[offset:offset + width], 'whole_section_integration_after_exact_partition')
                        if bounded(spec):
                            break
                        if width == 2:
                            reject_atomic(spec)
                            break
                        width -= 1
                    specs[spec['node_id']] = spec
                    following.append(spec['node_id'])
                    offset += width
                frontier = following
                level += 1
            section_assembly[sid] = frontier[0]
    terminal_assembly = [section_assembly[sid] for sid in ordered
                         if sid not in {p for s in sections for p in s['premise_section_ids']}]
    root_id = "root_" + payload_hash(materials[scope_id])[:24]
    root_inputs = {scope_id}
    for sid in roots:
        for dim in ('claims', 'lines'):
            for unit in section_cov[sid][dim]:
                root_inputs.update(bindings[dim][unit])
    specs[root_id] = spec_value(root_id, 'root', None, _empty(), root_inputs, terminal_assembly,
                               'final_scope_and_root_integration_after_local_reviews')
    if not bounded(specs[root_id]):
        reject_atomic(specs[root_id])
    plan = seal_plan(materials, {"source": expected, "assembly": expected},
        sorted({s["writer_execution_id"] for s in sections} | {r["execution_id"] for r in records}), [root_id],
        source_requirements={dim: {unit: refs for unit, refs in values.items() if refs}
                             for dim, values in requirements.items()}, node_ids=list(specs),
        node_input_requirements={nid: spec["input_ids"] for nid, spec in specs.items()},
        coverage_bindings=bindings, original_source_ids=list(source_ids.values()),
        dependency_scientific_views={nid: spec['scientific_view'] for nid, spec in specs.items()
                                     if 'scientific_view' in spec} or None,
        compact_dependency_nodes=[nid for nid, spec in specs.items() if spec['dependencies']]
                                if compact_dependencies else None)
    bundle = {"plan": plan, "materials": materials, "node_specs": specs,
              "rendered_sections": renders, "root_section_ids": roots, "root_node_id": root_id,
              "paper_ids": sorted(packet_map), "question_ids": sorted(questions),
              "section_assembly_nodes": section_assembly,
              "partitioned_review": True, "max_scientific_units": max_scientific_units,
              "merge_full_source": merge_full_source}
    bundle['dependency_delivery'] = DEPENDENCY_RECEIPT_SCHEMA if compact_dependencies else 'full-proof-json/1'
    return bundle
