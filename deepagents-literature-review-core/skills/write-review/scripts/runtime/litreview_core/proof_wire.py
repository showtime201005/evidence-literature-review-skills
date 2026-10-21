"""Lossless dictionary wire for complete hierarchical semantic proof tasks.

This is encoding, not a summary, proof approval, source filter or sharding.
Every original JSON value is restored and bound to the canonical task SHA256.
Repeated values and exact substrings of rendered text use readable references.
The model must review referenced CONTENT; child receipts never replace premises.
Only this module and its tests are initially integrated. A production caller
must deliver the guide, count the complete request, expand submitted IDs, and
still run the unchanged native scientific/identity/coverage acceptance gates.
"""
from __future__ import annotations

from collections import Counter, OrderedDict
import copy
from hashlib import sha256
import math
import re

from .task_store import canonical


SCHEMA = "hierarchical-proof-wire/1"
WIRE_GUIDE = {
    "task": "task is the complete hierarchical-proof-task/1, encoded without deleting or summarizing any value.",
    "references": "An exact string @N refers to dictionary['@N']; resolve recursively, including references used as object keys. @N is local to this one packet.",
    "literals": "A string beginning @@ is literal: remove exactly its first @. Other strings are literal. Dictionary entries obey the same rule.",
    "concatenation": "A singleton {$concat:[pieces]} is the exact concatenation of its resolved string pieces, with no added spaces or newlines. Offsets and hashes refer to the restored exact text.",
    "escaped_object": "A singleton {$literal:object} preserves a literal object whose own key would otherwise be a control tag; resolve that object's fields normally.",
    "review": "Read all content reached from task, including actual premise claims, complete original text when supplied, lines and retention obligations. A passed child receipt alone does not prove a new inference. Missing or failed dependencies remain missing or failed.",
    "submission": "Return the normal typed ProofSubmission shape. Use exact @N aliases from coverage/materials for unit IDs (or their full resolved strings). checked values and verdicts/issue unit_ids remain explicit arrays. Do not return dictionary references in place of these arrays. Reasons must contain your own substantive scientific review, not aliases alone.",
}
_CONTROL = {"$concat", "$literal"}
_REFERENCE = re.compile(r"@[0-9]+\Z")


def _literal(value):
    return "@"+value if value.startswith("@") else value


def _key_candidate(value):
    # Keep ordinary field names readable; only alias long identifiers/paths.
    return len(value) >= 32 or ("/" in value and len(value) >= 12)


def project_proof_task(packet):
    """Return complete, deterministic, canonically reversible model input.

    All declared dependencies and actual child payloads remain present exactly
    as supplied. This does not certify their validity. Repeated containers are
    interned, long string values/IDs have local aliases, and exact substring
    concatenation removes repeated render prose without removing rendered text.
    """
    if not isinstance(packet, dict) or packet.get("schema") != "hierarchical-proof-task/1":
        raise ValueError("Expected canonical hierarchical-proof-task/1")
    original = canonical(packet)  # Also rejects NaN, non-JSON objects, bad keys.
    strings, value_strings, eligible_keys, containers = Counter(), set(), set(), Counter()
    concat_targets, rendered_lines = set(), set()
    active = set()

    def scan(value, depth=0):
        if depth > 160:
            raise ValueError("Proof task nesting is too deep")
        if isinstance(value, str):
            strings[value] += 1
            value_strings.add(value)
        elif isinstance(value, (dict, list)):
            if id(value) in active:
                raise ValueError("Cyclic proof task")
            active.add(id(value))
            containers[sha256(canonical(value)).digest()] += 1
            if isinstance(value, dict):
                if any(not isinstance(key, str) for key in value):
                    raise ValueError("JSON object keys must be strings")
                for key in sorted(value):
                    strings[key] += 1
                    if _key_candidate(key):
                        eligible_keys.add(key)
                    scan(value[key], depth+1)
                # Scientific prose, quotes, original source paragraphs and
                # review reasons remain WHOLE literal dictionary entries.
                # Only host-rendered composites may concatenate existing whole
                # claims/lines, never a general word/token compression scheme.
                text = value.get("text")
                is_line = {"id", "text", "start_char", "end_char", "claim_ids"} <= set(value)
                if isinstance(text, str) and (is_line or value.get("schema") in {
                        "review-section-render/1", "mapped-review-render/1"}):
                    concat_targets.add(text)
                    if is_line:
                        rendered_lines.add(text)
            else:
                for item in value:
                    scan(item, depth+1)
            active.remove(id(value))
        elif value is not None and type(value) not in (bool, int, float):
            raise ValueError("Proof task must contain JSON values only")
        elif isinstance(value, float) and not math.isfinite(value):
            raise ValueError("Proof task numbers must be finite")
    scan(packet)
    pooled = sorted((text for text, count in strings.items()
                     if (text in value_strings or text in eligible_keys)
                     and ((len(text.encode("utf-8")) >= 12 and count >= 2) or len(text) >= 80)),
                    key=lambda text: (len(text), text))
    aliases = {text: "@"+str(index) for index, text in enumerate(pooled)}
    dictionary = {}
    # Literal candidates only: source/claim strings remain readable rather than
    # compressed bytes. Bound pattern memory and exclude self/cyclic matches.
    spans = sorted((text for text in pooled if len(text) >= 32 and (len(text) <= 4096 or text in rendered_lines)),
                   key=lambda text: (-len(text), text))
    pattern_cache = OrderedDict()

    def concatenate(text):
        if text not in concat_targets or len(text) < 80 or not spans:
            return _literal(text)
        threshold = len(text)-1
        if threshold not in pattern_cache:
            candidates = [candidate for candidate in spans if len(candidate) <= threshold]
            pattern_cache[threshold] = re.compile("|".join(re.escape(candidate) for candidate in candidates)) if candidates else None
            if len(pattern_cache) > 8:
                pattern_cache.popitem(last=False)
        pattern = pattern_cache[threshold]
        pattern_cache.move_to_end(threshold)
        if pattern is None:
            return _literal(text)
        pieces, end = [], 0
        for match in pattern.finditer(text):
            if match.start() > end:
                pieces.append(_literal(text[end:match.start()]))
            pieces.append(aliases[match.group()])
            end = match.end()
        if not pieces:
            return _literal(text)
        if end < len(text):
            pieces.append(_literal(text[end:]))
        projected = {"$concat": pieces}
        # A representation may be larger for a short one-off match. Keep the
        # exact literal in that case; no evidence content is ever shortened.
        return projected if len(canonical(projected)) < len(canonical(_literal(text))) else _literal(text)

    for text in pooled:
        dictionary[aliases[text]] = concatenate(text)
    memo = {}

    def encode(value):
        if isinstance(value, str):
            return aliases[value] if value in aliases else _literal(value)
        if isinstance(value, (dict, list)):
            fingerprint = sha256(canonical(value)).digest()
            if fingerprint in memo:
                return memo[fingerprint]
            if isinstance(value, dict):
                encoded = {(aliases[key] if key in aliases and _key_candidate(key) else _literal(key)): encode(value[key])
                           for key in sorted(value)}
                if len(encoded) == 1 and next(iter(encoded), None) in _CONTROL:
                    encoded = {"$literal": encoded}
            else:
                encoded = [encode(item) for item in value]
            if containers[fingerprint] >= 2 and len(canonical(encoded)) >= 24:
                ref = "@"+str(len(dictionary))
                dictionary[ref] = encoded
                memo[fingerprint] = ref
                return ref
            return encoded
        return value

    encoded_task = encode(packet)
    reached = set()
    def reachable(value):
        if isinstance(value, str):
            if _REFERENCE.fullmatch(value) and value not in reached:
                reached.add(value)
                reachable(dictionary[value])
        elif isinstance(value, dict):
            for key, item in value.items():
                reachable(key)
                reachable(item)
        elif isinstance(value, list):
            for item in value:
                reachable(item)
    reachable(encoded_task)
    wire = {"schema": SCHEMA, "guide": copy.deepcopy(WIRE_GUIDE),
            "canonical_sha256": sha256(original).hexdigest(), "canonical_json_bytes": len(original),
            "dictionary": {key: value for key, value in dictionary.items() if key in reached}, "task": encoded_task}
    if canonical(restore_proof_task(wire, max_expanded_bytes=max(64_000_000, len(original)))) != original:
        raise ValueError("Proof projection failed exact canonical roundtrip")
    return wire


class _Decoder:
    def __init__(self, wire, max_expanded_bytes):
        required = {"schema", "guide", "canonical_sha256", "canonical_json_bytes", "dictionary", "task"}
        if (not isinstance(wire, dict) or set(wire) != required or wire["schema"] != SCHEMA
                or wire["guide"] != WIRE_GUIDE):
            raise ValueError("Unsupported or malformed proof wire profile")
        if (type(max_expanded_bytes) is not int or max_expanded_bytes < 1
                or type(wire["canonical_json_bytes"]) is not int
                or not 0 <= wire["canonical_json_bytes"] <= max_expanded_bytes):
            raise ValueError("Proof wire expansion exceeds the permitted byte budget")
        if not isinstance(wire["canonical_sha256"], str) or re.fullmatch(r"[0-9a-f]{64}", wire["canonical_sha256"]) is None:
            raise ValueError("Invalid proof task SHA256")
        self.dictionary = wire["dictionary"]
        if not isinstance(self.dictionary, dict) or any(not isinstance(key, str) or not _REFERENCE.fullmatch(key)
                                                       for key in self.dictionary):
            raise ValueError("Invalid proof dictionary aliases")
        self.cache, self.active, self.costs = {}, set(), {}
        self.maximum, self.nodes = max_expanded_bytes, 0

    def decode(self, value, depth=0):
        if depth > 200:
            raise ValueError("Proof wire nesting is too deep")
        self.nodes += 1
        if self.nodes > 2_000_000:
            raise ValueError("Proof wire expansion has too many values")
        if isinstance(value, str):
            if value.startswith("@@"):
                return value[1:]
            if value.startswith("@"):
                if not _REFERENCE.fullmatch(value) or value not in self.dictionary:
                    raise ValueError("Unknown or malformed proof dictionary reference")
                if value in self.active:
                    raise ValueError("Cyclic proof dictionary")
                if value not in self.cache:
                    self.active.add(value)
                    try:
                        restored = self.decode(self.dictionary[value], depth+1)
                        size = len(canonical(restored))
                        if size > self.maximum:
                            raise ValueError("Proof dictionary value exceeds expansion budget")
                        self.cache[value], self.costs[value] = restored, size
                    finally:
                        self.active.remove(value)
                return copy.deepcopy(self.cache[value])
            return value
        if isinstance(value, dict):
            if set(value) == {"$concat"}:
                if not isinstance(value["$concat"], list):
                    raise ValueError("Concatenation requires an explicit list of strings")
                parts, size = [], 0
                for item in value["$concat"]:
                    part = self.decode(item, depth+1)
                    if not isinstance(part, str):
                        raise ValueError("Concatenation fragments must resolve to strings")
                    size += len(part.encode("utf-8"))
                    if size > self.maximum:
                        raise ValueError("Concatenation exceeds expansion budget")
                    parts.append(part)
                return "".join(parts)
            if set(value) == {"$literal"}:
                if not isinstance(value["$literal"], dict):
                    raise ValueError("Literal object escape requires an object")
                return self.object(value["$literal"], depth+1)
            return self.object(value, depth)
        if isinstance(value, list):
            return [self.decode(item, depth+1) for item in value]
        if value is None or type(value) in (bool, int) or (type(value) is float and math.isfinite(value)):
            return value
        raise ValueError("Proof wire must contain finite JSON values")

    def object(self, value, depth):
        out = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("Proof object keys must be strings")
            key = self.decode(key, depth+1)
            if not isinstance(key, str) or key in out:
                raise ValueError("Duplicate or non-string restored proof object key")
            out[key] = self.decode(item, depth+1)
        return out


def restore_proof_task(wire, *, max_expanded_bytes=64_000_000):
    """Restore exact canonical task values and reject corruption or bad refs."""
    decoder = _Decoder(wire, max_expanded_bytes)
    restored = decoder.decode(wire["task"])
    if set(decoder.cache) != set(decoder.dictionary):
        raise ValueError("Proof dictionary contains unreferenced values")
    if not isinstance(restored, dict) or restored.get("schema") != "hierarchical-proof-task/1":
        raise ValueError("Restored value is not a hierarchical proof task")
    encoded = canonical(restored)
    if len(encoded) != wire["canonical_json_bytes"] or sha256(encoded).hexdigest() != wire["canonical_sha256"]:
        raise ValueError("Proof wire does not restore its exact canonical SHA256/byte length")
    return restored


def proof_wire_stats(wire):
    """Report actual encoding complexity; it is not a model readability pass."""
    restore_proof_task(wire)
    counts = Counter()
    maximum_pieces, total_pieces = 0, 0
    dictionary = wire["dictionary"]
    def count(value):
        nonlocal maximum_pieces, total_pieces
        if isinstance(value, str):
            counts["references"] += bool(_REFERENCE.fullmatch(value))
        elif isinstance(value, list):
            for item in value:
                count(item)
        elif isinstance(value, dict):
            if set(value) == {"$concat"}:
                counts["concatenations"] += 1
                length = len(value["$concat"])
                maximum_pieces = max(maximum_pieces, length)
                total_pieces += length
            for key, item in value.items():
                count(key)
                count(item)
    count(wire["task"])
    for value in dictionary.values():
        count(value)
    memo = {}
    def depth(value):
        if isinstance(value, str) and _REFERENCE.fullmatch(value):
            if value not in memo:
                child_refs, child_concats = depth(dictionary[value])
                memo[value] = (child_refs+1, child_concats)
            return memo[value]
        if isinstance(value, (dict, list)):
            values = [*value.keys(), *value.values()] if isinstance(value, dict) else value
            children = [depth(item) for item in values]
            refs = max((item[0] for item in children), default=0)
            concats = max((item[1] for item in children), default=0)
            return refs, concats+int(isinstance(value, dict) and set(value) == {"$concat"})
        return 0, 0
    refs, concats = depth(wire["task"])
    return {"dictionary_entries": len(dictionary), "references": counts["references"],
            "concatenations": counts["concatenations"], "concatenation_pieces": total_pieces,
            "max_concatenation_pieces": maximum_pieces, "maximum_reference_chain": refs,
            "maximum_concat_nesting": concats,
            "canonical_json_bytes": wire["canonical_json_bytes"], "wire_json_bytes": len(canonical(wire)),
            "scientific_prose_policy": "Whole original/claim/quote/reason strings; concatenation only of host-rendered composites",
            "model_readability_and_semantic_quality_measured": False,
            "capacity": "Count this wire plus real child receipts, role docs, tool schemas, framing and output reservation before HTTP"}


def restore_submission_ids(submission, wire):
    """Expand ONLY typed responsibility-ID fields; never rewrite review prose.

    Normal native ProofSubmission validation and actual responsibility checks
    must follow. This function creates no verdict, issue, coverage or identity.
    Full original IDs are accepted; literal IDs beginning @ must be @@ escaped.
    """
    restore_proof_task(wire)
    decoder = _Decoder(wire, 64_000_000)
    if not isinstance(submission, dict):
        raise ValueError("Proof submission must be an object")
    result = copy.deepcopy(submission)

    def unit(value):
        if not isinstance(value, str):
            raise ValueError("Responsibility IDs must be strings")
        resolved = decoder.decode(value)
        if not isinstance(resolved, str):
            raise ValueError("Responsibility alias must resolve to a string")
        return resolved

    if not isinstance(result.get("checked"), dict):
        raise ValueError("checked must remain an explicit dimension object")
    for dim, values in result["checked"].items():
        if not isinstance(values, list):
            raise ValueError("checked dimensions must remain explicit ID arrays")
        result["checked"][dim] = [unit(value) for value in values]
    for field in ("verdicts", "issues"):
        if not isinstance(result.get(field), list):
            raise ValueError(field+" must remain an explicit array")
        for row in result[field]:
            if not isinstance(row, dict):
                raise ValueError(field+" rows must be objects")
            if field == "verdicts":
                row["unit_id"] = unit(row["unit_id"])
            else:
                if not isinstance(row.get("unit_ids"), list):
                    raise ValueError("Issue unit_ids must remain an explicit array")
                row["unit_ids"] = [unit(value) for value in row["unit_ids"]]
    return result
