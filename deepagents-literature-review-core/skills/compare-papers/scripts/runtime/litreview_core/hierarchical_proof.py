"""Versioned, fail-closed gates for bounded hierarchical review proofs.

This module checks declared coverage, bytes, provenance and model attestations;
it does not manufacture a semantic verdict.  ``RuntimeIdentity`` objects must
come from the host's real task/acceptance ledger, never from model JSON.  Their
output hashes bind the exact normalized submissions accepted by that host.
Exporting this ledger does not make it cryptographically authenticated.

Coverage is *direct responsibility*, not a repeated parent summary.  It must
partition each phase exactly; dependency closures provide the rollup.  A new
cross-group conclusion needs its own source-verifier attestation and original
source proofs in its closure.  A passed summary alone is never a source proof.
Existing v1/v2 review schemas and their gates are deliberately unaffected.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from hashlib import sha256
import json
import re
from types import MappingProxyType
from typing import Any, Mapping


SCHEMA_VERSION = "1.0.0"
PLAN_TYPE = "HierarchicalReviewProofPlan"
NODE_TYPE = "HierarchicalReviewProofNode"
DIMENSIONS = ("claims", "lines", "papers", "questions", "cells", "obligations")
PHASES = ("source", "assembly")
KINDS = {"source": "source", "cross_group": "source", "assembly": "assembly", "root": "assembly"}
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_ROLES = {"writer", "reader", "comparer", "coordinator", "source_verifier", "assembly_auditor"}
SCIENTIFIC_VIEWS_SCHEMA = "dependency-scientific-views/1"
SCIENTIFIC_VIEW_SCHEMA = "dependency-scientific-view/1"
DEPENDENCY_RECEIPT_SCHEMA = "dependency-proof-receipt/1"


class ProofError(ValueError):
    """A machine-readable proof rejection; no rejected proof is a completion."""

    def __init__(self, code: str, message: str, details: Any = None):
        super().__init__(message)
        self.code, self.details = code, details

    def as_dict(self) -> dict:
        return {"code": self.code, "message": str(self), "details": self.details}


def _fail(code: str, message: str, details: Any = None):
    raise ProofError(code, message, details)


def _id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        _fail("INVALID_ID", label + " must be a nonempty, unpadded string")
    return value


def _json_bytes(value: Any) -> bytes:
    def keys(item):
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                _fail("INVALID_PAYLOAD", "JSON object keys must be strings")
            for child in item.values():
                keys(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                keys(child)
    keys(value)
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        _fail("INVALID_PAYLOAD", "Payload is not canonical UTF-8 JSON", str(exc))


def payload_hash(value: Any) -> str:
    """Hash exact original bytes, or canonical JSON for an artifact payload.

    Pass Markdown as ``bytes`` to preserve its real source-version digest,
    including CRLF.  A JSON string is intentionally hashed as a JSON value.
    """
    return sha256(bytes(value) if isinstance(value, (bytes, bytearray)) else _json_bytes(value)).hexdigest()


def _hashes(value: Any, label: str) -> dict[str, str]:
    if not isinstance(value, Mapping):
        _fail("INVALID_HASHES", label + " must be an ID-to-SHA256 mapping")
    out = {}
    for key, digest in value.items():
        _id(key, label + " ID")
        if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
            _fail("INVALID_HASHES", label + " contains a non-SHA256 digest", key)
        out[key] = digest
    return dict(sorted(out.items()))


def _ids(value: Any, label: str, *, empty: bool = True) -> list[str]:
    if not isinstance(value, (list, tuple)):
        _fail("INVALID_COVERAGE", label + " must be a list")
    out = [_id(item, label + " item") for item in value]
    if len(set(out)) != len(out):
        _fail("DUPLICATE_COVERAGE", label + " contains duplicate IDs")
    if not empty and not out:
        _fail("EMPTY_DECLARATION", label + " cannot be empty")
    return sorted(out)


def _coverage(value: Any, label: str, *, fill: bool = False) -> dict[str, list[str]]:
    if not isinstance(value, Mapping) or set(value) - set(DIMENSIONS):
        _fail("INVALID_COVERAGE", label + " has an unknown coverage dimension")
    if not fill and set(value) != set(DIMENSIONS):
        _fail("INVALID_COVERAGE", label + " must explicitly declare all six dimensions")
    return {dim: _ids(value.get(dim, []), label + "." + dim) for dim in DIMENSIONS}


def dependency_view_material_id(node_id: str) -> str:
    return "dependency-view/" + _id(node_id, "scientific view parent")


def dependency_view_material(node_id: str, claims_by_dependency: Mapping[str, list[str]]) -> dict:
    """Canonical host-owned edge view, also delivered as a hashed input."""
    if not isinstance(claims_by_dependency, Mapping) or not claims_by_dependency:
        _fail("INVALID_SCIENTIFIC_VIEW", "A scientific view needs nonempty source dependency edges")
    children = {_id(child, "scientific view child"): _ids(claims, "selected claims", empty=False)
                for child, claims in claims_by_dependency.items()}
    if node_id in children:
        _fail("INVALID_SCIENTIFIC_VIEW", "A scientific view cannot select itself")
    return {"schema": SCIENTIFIC_VIEW_SCHEMA, "node_id": _id(node_id, "scientific view parent"),
            "claims_by_dependency": dict(sorted(children.items()))}


def _scientific_views(value: Any) -> dict[str, dict[str, list[str]]]:
    if not isinstance(value, dict) or set(value) != {"schema", "nodes"} or value["schema"] != SCIENTIFIC_VIEWS_SCHEMA:
        _fail("UNSUPPORTED_SCIENTIFIC_VIEW", "Expected the versioned dependency scientific-view contract")
    if not isinstance(value["nodes"], Mapping) or not value["nodes"]:
        _fail("INVALID_SCIENTIFIC_VIEW", "Declare at least one scientific-view parent")
    return {nid: dependency_view_material(nid, children)["claims_by_dependency"]
            for nid, children in value["nodes"].items()}


def _check_view_materials(p: dict, materials: Mapping[str, Any], node_ids=None):
    if "dependency_scientific_views" not in p:
        return
    for nid, children in _scientific_views(p["dependency_scientific_views"]).items():
        if node_ids is not None and nid not in node_ids:
            continue
        mid = dependency_view_material_id(nid)
        if materials.get(mid) != dependency_view_material(nid, children):
            _fail("SCIENTIFIC_VIEW_MATERIAL_MISMATCH", "Delivered edge view differs from the frozen plan", nid)


def _seal(kind: str, payload: dict) -> dict:
    # Roundtrip takes an immutable snapshot of the caller's containers.
    snapshot = json.loads(_json_bytes(payload))
    return {"schema_version": SCHEMA_VERSION, "artifact_type": kind,
            "payload": snapshot, "payload_hash": payload_hash(snapshot)}


def _open(value: Any, kind: str) -> dict:
    if not isinstance(value, dict) or set(value) != {"schema_version", "artifact_type", "payload", "payload_hash"}:
        _fail("INVALID_ENVELOPE", "Expected a sealed " + kind)
    if value["schema_version"] != SCHEMA_VERSION or value["artifact_type"] != kind:
        _fail("UNSUPPORTED_PROOF_VERSION", "Wrong proof kind or unsupported protocol version")
    if not isinstance(value["payload"], dict) or value["payload_hash"] != payload_hash(value["payload"]):
        _fail("PAYLOAD_TAMPERED", "Proof payload hash does not match")
    return value["payload"]


@dataclass(frozen=True)
class RuntimeIdentity:
    """Host-attested actual execution, delivered inputs, and accepted outputs.

    ``dependency_hashes`` records proof payloads actually delivered to the
    model, not just dependency names asserted in its output.  An ancestry
    entry is an inherited conversation/context, not merely a parent task ID.
    Ordinary coordinator parentage should use ``parent_context_id`` instead.
    """

    execution_id: str
    context_id: str
    role: str
    input_hashes: Mapping[str, str]
    dependency_hashes: Mapping[str, str] = field(default_factory=dict)
    output_hashes: Mapping[str, str] = field(default_factory=dict)
    ancestor_context_ids: tuple[str, ...] = ()
    run_id: str = ""
    task_call_id: str = ""
    parent_context_id: str = ""
    delivered_dependency_receipt_hashes: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self):
        _id(self.execution_id, "execution_id")
        _id(self.context_id, "context_id")
        role = {"verifier": "source_verifier", "source-verifier": "source_verifier",
                "auditor": "assembly_auditor", "assembly-auditor": "assembly_auditor"}.get(self.role, self.role)
        if role not in _ROLES:
            _fail("INVALID_IDENTITY", "Unknown runtime role", role)
        object.__setattr__(self, "role", role)
        for name in ("input_hashes", "dependency_hashes", "output_hashes", "delivered_dependency_receipt_hashes"):
            object.__setattr__(self, name, MappingProxyType(_hashes(getattr(self, name), name)))
        ancestors = tuple(_ids(self.ancestor_context_ids, "ancestor_context_ids"))
        if self.context_id in ancestors:
            _fail("INVALID_IDENTITY", "A context cannot inherit itself")
        object.__setattr__(self, "ancestor_context_ids", ancestors)


def seal_plan(materials: Mapping[str, Any], expected_coverage: Mapping[str, Mapping],
              writer_execution_ids: list[str], roots: list[str], *,
              source_requirements: Mapping[str, Any],
              node_ids: list[str] | None = None,
              node_input_requirements: Mapping[str, list[str]] | None = None,
              coverage_bindings: Mapping[str, Mapping[str, list[str]]] | None = None,
              original_source_ids: list[str] | None = None,
              dependency_scientific_views: Mapping[str, Mapping[str, list[str]]] | None = None,
              compact_dependency_nodes: list[str] | None = None) -> dict:
    """Freeze expected coverage and its real material/source dependencies.

    ``source_requirements`` accepts ``{claim_id: [source_id]}`` or mappings
    nested under coverage dimensions.  Every source-phase claim needs an
    explicit, nonempty original-source requirement.  Obligations also need
    requirements when declared in the source phase.  ``coverage_bindings``
    binds each coverage unit to its actual target/context material IDs;
    identical material/unit IDs are inferred for convenience.
    ``node_ids`` and ``node_input_requirements`` must declare every intended
    node and its complete research input set, including necessary context.
    ``dependency_scientific_views`` opts selected cross-group edges into the
    versioned mapped-target contract. Each parent must actually receive its
    canonical ``dependency_view_material`` under ``dependency_view_material_id``.
    Omitting this argument preserves the original strict child-science rule.
    """
    if not isinstance(materials, Mapping) or not materials:
        _fail("INVALID_MATERIALS", "A proof plan needs actual immutable materials")
    hashes = {_id(key, "material ID"): payload_hash(value) for key, value in materials.items()}
    if not isinstance(expected_coverage, Mapping) or set(expected_coverage) != set(PHASES):
        _fail("INVALID_COVERAGE", "Declare both source and assembly coverage")
    expected = {phase: _coverage(expected_coverage[phase], phase, fill=True) for phase in PHASES}
    req = _requirements(source_requirements)
    source_ids = _ids(original_source_ids if original_source_ids is not None else
                      sorted(mid for mid, value in materials.items() if isinstance(value, bytes)),
                      "original_source_ids", empty=False)
    bindings = {dim: {} for dim in DIMENSIONS}
    supplied = coverage_bindings or {}
    if not isinstance(supplied, Mapping) or set(supplied) - set(DIMENSIONS):
        _fail("INVALID_BINDINGS", "Unknown coverage binding dimension")
    for dim in DIMENSIONS:
        declared = set(expected["source"][dim]) | set(expected["assembly"][dim])
        supplied_dim = supplied.get(dim, {})
        if not isinstance(supplied_dim, Mapping) or set(supplied_dim) - declared:
            _fail("INVALID_BINDINGS", "Binding references an undeclared unit", dim)
        for unit in sorted(declared):
            values = supplied_dim.get(unit, [unit] if unit in hashes else [])
            bindings[dim][unit] = _ids(values, "coverage binding " + unit, empty=False)
    payload = {"material_hashes": hashes, "expected_coverage": expected,
        "writer_execution_ids": _ids(writer_execution_ids, "writer_execution_ids", empty=False),
        "roots": _ids(roots, "roots", empty=False), "original_source_ids": source_ids,
        "source_requirements": req, "coverage_bindings": bindings,
        "node_ids": _ids(node_ids or [], "node_ids", empty=False),
        "node_input_requirements": node_input_requirements or {}}
    if dependency_scientific_views is not None:
        if not isinstance(dependency_scientific_views, Mapping) or not dependency_scientific_views:
            _fail("INVALID_SCIENTIFIC_VIEW", "Selected dependency views must be a nonempty parent mapping")
        payload["dependency_scientific_views"] = {"schema": SCIENTIFIC_VIEWS_SCHEMA,
            "nodes": {nid: dependency_view_material(nid, children)["claims_by_dependency"]
                      for nid, children in dependency_scientific_views.items()}}
    if compact_dependency_nodes is not None:
        payload["dependency_delivery"] = {"schema": DEPENDENCY_RECEIPT_SCHEMA,
                                          "node_ids": _ids(compact_dependency_nodes, "compact dependency nodes", empty=False)}
    plan = _seal(PLAN_TYPE, payload)
    _check_plan(_open(plan, PLAN_TYPE))
    _check_view_materials(payload, materials)
    return plan


def _requirements(value: Any) -> dict:
    if not isinstance(value, Mapping):
        _fail("INVALID_SOURCE_REQUIREMENTS", "source_requirements must be a mapping")
    nested = bool(value) and all(key in DIMENSIONS and isinstance(item, Mapping) for key, item in value.items())
    source = value if nested else {"claims": value}
    if set(source) - set(DIMENSIONS):
        _fail("INVALID_SOURCE_REQUIREMENTS", "Unknown source requirement dimension")
    out = {dim: {} for dim in DIMENSIONS}
    for dim, units in source.items():
        if not isinstance(units, Mapping):
            _fail("INVALID_SOURCE_REQUIREMENTS", "Requirements must map units to sources")
        out[dim] = {_id(unit, "source requirement ID"): _ids(ids, "sources for " + unit, empty=False)
                    for unit, ids in units.items()}
    return out


def _check_plan(p: dict):
    required_keys = {"material_hashes", "expected_coverage", "writer_execution_ids", "roots",
                  "original_source_ids", "source_requirements", "coverage_bindings",
                  "node_ids", "node_input_requirements"}
    if not required_keys <= set(p) or set(p) - required_keys - {"dependency_scientific_views", "dependency_delivery"}:
        _fail("INVALID_PLAN", "Unknown or missing plan field")
    hashes = _hashes(p["material_hashes"], "material_hashes")
    if not hashes or set(p["expected_coverage"]) != set(PHASES):
        _fail("INVALID_PLAN", "Incomplete plan declaration")
    expected = {phase: _coverage(p["expected_coverage"][phase], phase) for phase in PHASES}
    for dim in ("claims", "lines", "cells", "obligations"):
        if set(expected["source"][dim]) != set(expected["assembly"][dim]):
            _fail("SOURCE_COVERAGE_MISMATCH", "Final scientific/output units require both source and assembly coverage", dim)
    _ids(p["roots"], "roots", empty=False)
    _ids(p["writer_execution_ids"], "writer_execution_ids", empty=False)
    node_ids = set(_ids(p["node_ids"], "node_ids", empty=False))
    if not set(p["roots"]) <= node_ids:
        _fail("INVALID_NODE_INVENTORY", "A declared root is outside the planned node inventory")
    input_requirements = p["node_input_requirements"]
    if not isinstance(input_requirements, Mapping) or set(input_requirements) != node_ids:
        _fail("INVALID_NODE_INPUT_REQUIREMENTS", "Every planned node needs its exact target/context input inventory")
    for nid, ids in input_requirements.items():
        if not set(_ids(ids, "node inputs for " + nid, empty=False)) <= set(hashes):
            _fail("UNKNOWN_MATERIAL", "A planned node input is outside the material inventory", nid)
    originals = set(_ids(p["original_source_ids"], "original_source_ids", empty=False))
    if not originals <= set(hashes):
        _fail("UNKNOWN_MATERIAL", "An original source is not in the material inventory")
    req = _requirements(p["source_requirements"])
    if set(p["source_requirements"]) != set(DIMENSIONS) or set(p["coverage_bindings"]) != set(DIMENSIONS):
        _fail("INVALID_PLAN", "Requirements/bindings must declare all dimensions")
    for dim in DIMENSIONS:
        expected_source = set(expected["source"][dim])
        if set(req[dim]) - expected_source:
            _fail("INVALID_SOURCE_REQUIREMENTS", "Source requirement has an unknown source-phase unit", dim)
        if dim in {"claims", "obligations"} and set(req[dim]) != expected_source:
            _fail("MISSING_SOURCE_REQUIREMENT", "Every source-phase " + dim + " unit needs original sources")
        for ids in req[dim].values():
            if not set(ids) <= originals:
                _fail("NOT_ORIGINAL_SOURCE", "A scientific source requirement references a summary/unknown source")
        declared = set(expected["source"][dim]) | set(expected["assembly"][dim])
        mapping = p["coverage_bindings"][dim]
        if not isinstance(mapping, Mapping) or set(mapping) != declared:
            _fail("INVALID_BINDINGS", "Every expected coverage unit needs exact material bindings", dim)
        for unit, ids in mapping.items():
            bindings = set(_ids(ids, "bindings for " + unit, empty=False))
            if not bindings <= set(hashes):
                _fail("UNKNOWN_MATERIAL", "A coverage binding names unknown material", unit)
            if dim in {"claims", "lines", "cells", "obligations"} and not bindings - originals:
                _fail("MISSING_TARGET_BINDING", "Scientific/output units need their real target material", unit)
    if "dependency_scientific_views" in p:
        for nid, children in _scientific_views(p["dependency_scientific_views"]).items():
            if nid not in node_ids or not set(children) <= node_ids:
                _fail("INVALID_SCIENTIFIC_VIEW", "An edge references an unplanned node", nid)
            mid = dependency_view_material_id(nid)
            if mid not in hashes or mid not in input_requirements[nid]:
                _fail("SCIENTIFIC_VIEW_NOT_BOUND", "A scientific view must be an immutable actual parent input", nid)
            for claims in children.values():
                if not set(claims) <= set(expected["source"]["claims"]):
                    _fail("UNKNOWN_SCIENTIFIC_PREMISE", "A selected premise is outside the scientific claim inventory", nid)
    if "dependency_delivery" in p:
        delivery = p["dependency_delivery"]
        if (not isinstance(delivery, dict) or set(delivery) != {"schema", "node_ids"}
                or delivery["schema"] != DEPENDENCY_RECEIPT_SCHEMA):
            _fail("UNSUPPORTED_DEPENDENCY_DELIVERY", "Unknown compact dependency delivery protocol")
        if not set(_ids(delivery["node_ids"], "compact dependency nodes", empty=False)) <= node_ids:
            _fail("INVALID_DEPENDENCY_DELIVERY", "Compact delivery references an unplanned node")


def dependency_receipt(node: dict) -> dict:
    """Exact versioned projection, not validation or a new semantic approval.

    Only prepare_dependency_receipts may authorize delivery after complete host
    closure preflight. The gate also uses this pure reconstruction to compare
    the receipt bytes actually bound by a trusted RuntimeIdentity.
    """
    n = _open(node, NODE_TYPE)
    _check_node(n)
    return {"schema": DEPENDENCY_RECEIPT_SCHEMA, "node_id": n["node_id"], "kind": n["kind"],
            "status": n["status"], "reason": n["reason"], "issues": json.loads(_json_bytes(n["issues"])),
            "coverage": json.loads(_json_bytes(n["coverage"])), "proof_payload_hash": node["payload_hash"]}


def _bound_target(p, materials, dim, unit, predicate, label):
    matches = [materials[mid] for mid in p["coverage_bindings"][dim].get(unit, [])
               if isinstance(materials[mid], dict) and predicate(materials[mid])]
    if len(matches) != 1:
        _fail("INVALID_SCIENTIFIC_TARGET", "Scientific views require one actual typed " + label + " binding", unit)
    return matches[0]


def _required_view_premises(n: dict, p: dict, materials: Mapping[str, Any]) -> set[str]:
    """Reconstruct dependencies from actual mapped targets, never prose hints.

    This opt-in v1 contract supports the mapped claim/line/cell/disposition
    records produced by the compiler. Opaque legacy targets remain supported
    through the unchanged strict-all-child-science path.
    """
    target_claims, required = set(n["coverage"]["claims"]), set()
    for unit in n["coverage"]["lines"]:
        value = _bound_target(p, materials, "lines", unit,
            lambda v: v.get("id") == unit and "claim_ids" in v and isinstance(v.get("text"), str), "rendered line")
        target_claims.update(_ids(value["claim_ids"], "actual line claim IDs"))
    for unit in n["coverage"]["cells"]:
        value = _bound_target(p, materials, "cells", unit,
            lambda v: "global_claim_ids" in v and "claim_ids" in v and isinstance(v.get("section_id"), str), "comparison cell")
        local_ids = _ids(value["claim_ids"], "actual cell local claim IDs", empty=False)
        global_ids = _ids(value["global_claim_ids"], "actual cell global claim IDs", empty=False)
        if set(global_ids) != {value["section_id"] + "/" + cid for cid in local_ids}:
            _fail("INVALID_SCIENTIFIC_TARGET", "Cell global IDs differ from its actual local claim links", unit)
        target_claims.update(global_ids)
    for unit in n["coverage"]["obligations"]:
        value = _bound_target(p, materials, "obligations", unit,
            lambda v: isinstance(v.get("definition"), dict) and isinstance(v.get("disposition"), dict)
                      and isinstance(v.get("section_id"), str), "obligation disposition")
        definition, disposition = value["definition"], value["disposition"]
        premise = definition.get("premise_claim_id")
        if definition.get("kind") == "premise_retention" and premise is None:
            _fail("INVALID_SCIENTIFIC_TARGET", "A premise-retention duty lacks its actual premise claim", unit)
        if premise is not None:
            required.add(_id(premise, "actual obligation premise claim"))
        status = disposition.get("status")
        if status not in {"included", "excluded"}:
            _fail("INVALID_SCIENTIFIC_TARGET", "Scientific retention needs an actual included/excluded disposition", unit)
        target_claims.update(value["section_id"] + "/" + cid
                             for cid in _ids(disposition.get("claim_ids"), "actual disposition claim IDs"))
        if status == "excluded":
            # Exclusion must be assessed against the complete actual candidate
            # section as well as the omitted premise; a reason alone is not a
            # scientific disposition. Planner delivers these complete claims.
            target_claims.update(cid for cid in p["expected_coverage"]["source"]["claims"]
                                 if cid.startswith(value["section_id"] + "/"))
    for cid in target_claims:
        if cid not in p["coverage_bindings"]["claims"]:
            _fail("UNKNOWN_SCIENTIFIC_TARGET", "Line/cell/disposition references an undeclared actual claim", cid)
        if not set(p["coverage_bindings"]["claims"][cid]) <= set(n["inputs"]):
            _fail("MISSING_SCIENTIFIC_TARGET", "An actual linked target claim/context was not delivered", cid)
        value = _bound_target(p, materials, "claims", cid,
                              lambda v: v.get("claim_id") == cid and "premise_claim_ids" in v, "claim")
        required.update(_ids(value["premise_claim_ids"], "actual target scientific premises", empty=False))
    if not required:
        _fail("EMPTY_SCIENTIFIC_VIEW", "A selected scientific view needs actual target premises", n["node_id"])
    return required


def seal_node(node_id: str, kind: str, execution_id: str, inputs: Mapping[str, str],
              dependencies: Mapping[str, str], coverage: Mapping[str, list[str]],
              status: str, reason: str, issues: list | None = None) -> dict:
    """Seal an actual verifier/auditor submission; this does not approve it."""
    p = {"node_id": _id(node_id, "node_id"), "kind": kind,
         "execution_id": _id(execution_id, "execution_id"),
         "inputs": _hashes(inputs, "inputs"), "dependencies": _hashes(dependencies, "dependencies"),
         "coverage": _coverage(coverage, "node coverage", fill=True),
         "status": status, "reason": reason, "issues": [] if issues is None else issues}
    _check_node(p)
    return _seal(NODE_TYPE, p)


def _check_node(p: dict):
    if set(p) != {"node_id", "kind", "execution_id", "inputs", "dependencies", "coverage", "status", "reason", "issues"}:
        _fail("INVALID_NODE", "Unknown or missing node field")
    _id(p["node_id"], "node_id")
    _id(p["execution_id"], "execution_id")
    if not isinstance(p["kind"], str) or p["kind"] not in KINDS:
        _fail("INVALID_NODE_KIND", "Unknown node kind")
    _hashes(p["inputs"], "inputs")
    _hashes(p["dependencies"], "dependencies")
    _coverage(p["coverage"], "node coverage")
    if not p["inputs"]:
        _fail("MISSING_INPUT", "Every node must bind its actual target/context inputs")
    if not isinstance(p["status"], str) or p["status"] not in {"passed", "needs_revision", "unresolved", "failed"}:
        _fail("INVALID_STATUS", "Unknown semantic node status")
    if not isinstance(p["reason"], str) or not p["reason"].strip():
        _fail("EMPTY_REASON", "A semantic attestation needs a concrete nonempty reason")
    if not isinstance(p["issues"], list):
        _fail("INVALID_ISSUES", "issues must be an explicit list")


def verify_proof(plan: dict, nodes: Mapping[str, dict] | list[dict], materials: Mapping[str, Any],
                 identities: Mapping[str, RuntimeIdentity], *, _dependency_roots=None) -> dict:
    """Return a mechanical acceptance receipt, or raise ``ProofError``.

    The caller supplies *current actual material contents*, not just expected
    hashes.  Raw original sources must be bytes.  Source-phase scientific
    units must bind sources actually delivered to independent source models.
    ``cross_group`` nodes may use source-node closures for bounded original
    source verification, but never assembly-only or summary-only ancestry.
    """
    p = _open(plan, PLAN_TYPE)
    _check_plan(p)
    if not isinstance(materials, Mapping) or set(materials) != set(p["material_hashes"]):
        _fail("MATERIAL_INVENTORY_MISMATCH", "Current materials differ from the frozen inventory")
    partial = _dependency_roots is not None
    scientific_views = (_scientific_views(p["dependency_scientific_views"])
                        if "dependency_scientific_views" in p else {})
    originals = set(p["original_source_ids"])

    if not isinstance(identities, Mapping) or any(type(item) is not RuntimeIdentity for item in identities.values()):
        _fail("UNTRUSTED_IDENTITY", "Only host-supplied RuntimeIdentity objects are accepted")
    context_owners = {}
    for eid, identity in identities.items():
        if eid != identity.execution_id:
            _fail("IDENTITY_KEY_MISMATCH", "Runtime identity key is not its execution ID")
        owner = context_owners.setdefault(identity.context_id, eid)
        if owner != eid:
            _fail("CONTEXT_ALIAS", "Two executions claim the same real context", identity.context_id)
    writers = []
    for wid in p["writer_execution_ids"]:
        identity = identities.get(wid)
        if identity is None or identity.role not in {"writer", "reader", "comparer"}:
            _fail("UNTRUSTED_WRITER", "A writer origin lacks a runtime identity", wid)
        writers.append(identity.context_id)

    if isinstance(nodes, Mapping):
        items = list(nodes.items())
    elif isinstance(nodes, list):
        items = [(None, node) for node in nodes]
    else:
        _fail("INVALID_NODES", "nodes must be a mapping or list of sealed nodes")
    opened, seals = {}, {}
    for key, node in items:
        n = _open(node, NODE_TYPE)
        _check_node(n)
        nid = n["node_id"]
        if key is not None and key != nid:
            _fail("NODE_ID_MISMATCH", "Node dictionary key differs from payload ID")
        if nid in opened:
            _fail("DUPLICATE_NODE", "Duplicate proof node", nid)
        opened[nid], seals[nid] = n, node
    if not opened:
        _fail("MISSING_NODE", "No proof nodes were supplied")
    unknown = set(opened) - set(p["node_ids"])
    if unknown:
        _fail("UNKNOWN_NODE", "Supplied proof contains unplanned nodes", sorted(unknown))
    missing_nodes = set(p["node_ids"]) - set(opened)
    if missing_nodes and not partial:
        _fail("MISSING_NODE", "Planned proof nodes are absent", sorted(missing_nodes))
    checked_roots = _ids(_dependency_roots, "dependency closure roots", empty=False) if partial else p["roots"]
    if partial:
        if not set(checked_roots) <= set(opened):
            _fail("MISSING_DEPENDENCY", "Requested dependency closure is incomplete")
    else:
        for root in p["roots"]:
            if root not in opened or opened[root]["kind"] != "root":
                _fail("MISSING_ROOT", "A declared root is absent or not a root node", root)
        if {nid for nid, n in opened.items() if n["kind"] == "root"} != set(p["roots"]):
            _fail("UNDECLARED_ROOT", "Root nodes must exactly match the declared roots")
    relevant_materials = (set().union(*(set(n["inputs"]) for n in opened.values()))
                          if partial else set(materials))
    for mid in relevant_materials:
        if mid not in p["material_hashes"]:
            _fail("UNKNOWN_MATERIAL", "A dependency input is outside the sealed material inventory", mid)
        if payload_hash(materials[mid]) != p["material_hashes"][mid]:
            _fail("STALE_MATERIAL", "Current material bytes/payload changed", mid)
    _check_view_materials(p, materials, set(opened) if partial else None)
    for mid in originals & relevant_materials:
        if not isinstance(materials[mid], bytes):
            _fail("ORIGINAL_SOURCE_BYTES_REQUIRED", "Pass exact original source bytes", mid)

    # Inspect all supplied nodes, including orphans, before trusting any status.
    states, order, closures = {}, [], {}
    def visit(nid):
        if states.get(nid) == 1:
            _fail("GRAPH_CYCLE", "Proof graph contains a cycle", nid)
        if states.get(nid) == 2:
            return closures[nid]
        states[nid] = 1
        descendants = set()
        for dep in opened[nid]["dependencies"]:
            if dep not in opened:
                _fail("MISSING_DEPENDENCY", "A proof dependency is absent", dep)
            descendants.add(dep)
            descendants.update(visit(dep))
        states[nid] = 2
        closures[nid] = descendants
        order.append(nid)
        return descendants
    for nid in opened:
        visit(nid)
    reachable = set(checked_roots)
    for root in checked_roots:
        reachable.update(closures[root])
    if reachable != set(opened):
        _fail("ORPHAN_NODE", "A supplied node is outside the required proof graph", sorted(set(opened) - reachable))

    seen = {phase: {dim: Counter() for dim in DIMENSIONS} for phase in PHASES}
    source_sets = {}
    for nid in order:
        n = opened[nid]
        if nid in scientific_views and n["kind"] != "cross_group":
            _fail("INVALID_SCIENTIFIC_VIEW", "Only cross-group source proofs may use selected scientific edges", nid)
        identity = identities.get(n["execution_id"])
        if identity is None:
            _fail("UNTRUSTED_IDENTITY", "Node execution has no trusted runtime registration", nid)
        phase = KINDS[n["kind"]]
        needed_role = "source_verifier" if phase == "source" else "assembly_auditor"
        if identity.role != needed_role:
            _fail("ROLE_MISMATCH", "Runtime role cannot issue this proof", nid)
        if identity.context_id in writers or set(identity.ancestor_context_ids) & set(writers):
            _fail("WRITER_NOT_INDEPENDENT", "Verifier inherited or shares a writer context", nid)
        if identity.output_hashes.get(nid) != seals[nid]["payload_hash"]:
            _fail("UNATTESTED_OUTPUT", "Node is not the exact runtime-accepted model submission", nid)
        if n["status"] != "passed" or n["issues"]:
            _fail("SEMANTIC_REVIEW_FAILED", "An unresolved, failed or issue-bearing node cannot pass", nid)
        for mid, digest in n["inputs"].items():
            if mid not in p["material_hashes"]:
                _fail("UNKNOWN_MATERIAL", "Node references unknown material", mid)
            if digest != p["material_hashes"][mid]:
                _fail("STALE_INPUT", "Node input differs from the current frozen material", mid)
            if identity.input_hashes.get(mid) != digest:
                _fail("INPUT_NOT_DELIVERED", "Runtime did not deliver the claimed input bytes/payload", mid)
        required_inputs = set(p["node_input_requirements"][nid])
        if set(n["inputs"]) != required_inputs:
            _fail("NODE_INPUT_SET_MISMATCH", "Node did not bind its complete planned target/context input set", nid)
        runtime_research_inputs = set(identity.input_hashes) & set(p["material_hashes"])
        if runtime_research_inputs != set(n["inputs"]):
            _fail("UNBOUND_RUNTIME_INPUT", "Runtime research inputs are missing from the proof's dependency bindings", nid)
        compact_nodes = set(p.get("dependency_delivery", {}).get("node_ids", []))
        receipt_hashes = identity.delivered_dependency_receipt_hashes
        if nid in compact_nodes:
            if not n["dependencies"] or set(receipt_hashes) != set(n["dependencies"]):
                _fail("DEPENDENCY_RECEIPT_NOT_DELIVERED", "Compact parents must bind every and only actually delivered receipt", nid)
        elif receipt_hashes:
            _fail("UNDECLARED_DEPENDENCY_RECEIPT", "Legacy full-proof delivery cannot silently become receipt delivery", nid)
        for dep, digest in n["dependencies"].items():
            if digest != seals[dep]["payload_hash"]:
                _fail("STALE_DEPENDENCY", "A dependency proof was changed or replayed", dep)
            if identity.dependency_hashes.get(dep) != digest:
                _fail("DEPENDENCY_NOT_DELIVERED", "Runtime did not deliver a required child proof", dep)
            if nid in compact_nodes and receipt_hashes[dep] != payload_hash(dependency_receipt(seals[dep])):
                _fail("DEPENDENCY_RECEIPT_MISMATCH", "Actual compact receipt differs from the true complete child proof", dep)
        for dim, units in n["coverage"].items():
            expected = set(p["expected_coverage"][phase][dim])
            if not set(units) <= expected:
                _fail("UNKNOWN_COVERAGE", "Node claims an undeclared coverage unit", {"node": nid, "dimension": dim})
            seen[phase][dim].update(units)
            for unit in units:
                bound = set(p["coverage_bindings"][dim][unit])
                if not bound <= set(n["inputs"]):
                    _fail("MISSING_TARGET_INPUT", "Coverage does not bind all actual target/context material", unit)
        if phase == "source":
            # Only source-verifier ancestry can discharge original-source work.
            if any(KINDS[opened[dep]["kind"]] != "source" for dep in n["dependencies"]):
                _fail("INVALID_SOURCE_DEPENDENCY", "Scientific source proof cannot rely on assembly approval", nid)
            if not any(n["coverage"][dim] for dim in ("claims", "cells", "obligations")):
                _fail("EMPTY_SOURCE_ATTESTATION", "Source proof must assess a scientific claim/cell/obligation", nid)
            delivered_sources = set(n["inputs"]) & originals
            source_sets[nid] = set()
            if n["kind"] == "source" and n["dependencies"]:
                _fail("INVALID_SOURCE_DEPENDENCY", "A direct source leaf cannot outsource its original inputs", nid)
            if n["kind"] == "cross_group":
                if not n["dependencies"]:
                    _fail("MISSING_SOURCE_PROOF", "Cross-group conclusions need original-source child proofs", nid)
                premises = set()
                if nid in scientific_views:
                    view = scientific_views[nid]
                    if set(view) != set(n["dependencies"]):
                        _fail("SCIENTIFIC_VIEW_DEPENDENCIES_MISMATCH", "Views must name every and only actual source dependency", nid)
                    actual_required = _required_view_premises(n, p, materials)
                    selected = [cid for claims in view.values() for cid in claims]
                    if len(selected) != len(set(selected)):
                        _fail("DUPLICATE_SCIENTIFIC_PREMISE", "A scientific premise must be certified by exactly one selected child", nid)
                    if set(selected) != actual_required:
                        _fail("SCIENTIFIC_PREMISE_VIEW_MISMATCH", "Selected claims differ from actual target/premise-retention requirements",
                              {"node": nid, "missing": sorted(actual_required - set(selected)),
                               "unknown": sorted(set(selected) - actual_required)})
                    for dep, claims in view.items():
                        if not set(claims) <= set(opened[dep]["coverage"]["claims"]):
                            _fail("UNCERTIFIED_SCIENTIFIC_PREMISE", "A selected claim was not actually covered by its passed child", dep)
                        for cid in claims:
                            premises.update(p["coverage_bindings"]["claims"][cid])
                            required_sources = set(p["source_requirements"]["claims"][cid])
                            if not required_sources <= source_sets[dep]:
                                _fail("MISSING_ORIGINAL_SOURCE", "Selected premise lacks its certified original-source closure", cid)
                            source_sets[nid].update(required_sources)
                else:
                    # Legacy plans retain the original strict contract.
                    for dep in n["dependencies"]:
                        source_sets[nid].update(source_sets[dep])
                        for dim in ("claims", "cells", "obligations"):
                            for unit in opened[dep]["coverage"][dim]:
                                premises.update(p["coverage_bindings"][dim][unit])
                if not premises <= set(n["inputs"]):
                    _fail("MISSING_SCIENTIFIC_PREMISES", "Cross-group verifier received proof hashes but not the actual certified scientific premises/counterevidence", sorted(premises - set(n["inputs"])))
            for dim, units in n["coverage"].items():
                for unit in units:
                    required = set(p["source_requirements"][dim].get(unit, []))
                    if not required <= delivered_sources | source_sets[nid]:
                        _fail("MISSING_ORIGINAL_SOURCE", "Claim/obligation lacks required original-source proof", unit)
                    source_sets[nid].update(required)
            if not source_sets[nid]:
                _fail("MISSING_ORIGINAL_SOURCE", "A source proof has no original bytes in its lineage", nid)
        else:
            source_ancestors = [opened[dep] for dep in closures[nid] if KINDS[opened[dep]["kind"]] == "source"]
            if not source_ancestors:
                _fail("MISSING_SOURCE_PROOF", "Assembly proof has no original-source verification lineage", nid)
            source_contexts = {identities[item["execution_id"]].context_id for item in source_ancestors}
            if identity.context_id in source_contexts or set(identity.ancestor_context_ids) & source_contexts:
                _fail("ASSEMBLY_NOT_INDEPENDENT", "Assembly auditor shares or inherited a source-verifier context", nid)
            # A local assembly claim must have its own source-phase unit in the closure.
            for dim in ("claims", "lines", "cells", "obligations"):
                required = set(n["coverage"][dim]) & set(p["expected_coverage"]["source"][dim])
                covered = {unit for dep in source_ancestors for unit in dep["coverage"][dim]}
                if not required <= covered:
                    _fail("MISSING_LOCAL_SOURCE_PROOF", "Local assembly omits source proofs for its own units", nid)

    counts = {phase: {} for phase in PHASES}
    for phase in PHASES:
        for dim in DIMENSIONS:
            expected = set(p["expected_coverage"][phase][dim])
            duplicates = sorted(unit for unit, count in seen[phase][dim].items() if count != 1)
            if duplicates:
                _fail("DUPLICATE_COVERAGE", "Direct proof responsibilities overlap", {"phase": phase, "dimension": dim, "ids": duplicates})
            missing = sorted(expected - set(seen[phase][dim]))
            if missing and not partial:
                _fail("MISSING_COVERAGE", "Required proof coverage is incomplete", {"phase": phase, "dimension": dim, "ids": missing})
            counts[phase][dim] = len(seen[phase][dim]) if partial else len(expected)
    verified_sources = set().union(*source_sets.values())
    if originals - verified_sources and not partial:
        _fail("MISSING_ORIGINAL_SOURCE", "Some declared original sources have no scientific source proof", sorted(originals - verified_sources))
    if partial:
        return {"schema": "dependency-closure-preflight/1", "status": "dependency_closure_validated",
                "publication_verified": False, "plan_hash": plan["payload_hash"],
                "node_hashes": {nid: seals[nid]["payload_hash"] for nid in sorted(opened)},
                "dependency_roots": checked_roots, "original_sources_verified": sorted(verified_sources)}
    return {"schema_version": SCHEMA_VERSION, "artifact_type": "HierarchicalReviewProofReceipt",
            "status": "passed", "plan_hash": plan["payload_hash"],
            "node_hashes": {nid: seals[nid]["payload_hash"] for nid in sorted(opened)},
            "roots": p["roots"], "coverage_counts": counts,
            "original_sources_verified": sorted(verified_sources),
            "verification_method": "independent_model_hierarchical_review",
            "semantic_attestation": "Actual runtime-bound model verdicts; not human review or a proof of comprehension."}


def verify_dependency_closure(plan, nodes, materials, identities, dependency_ids):
    """Validate actual completed children and every ancestor before delivery.

    This shares the final gate's node/material/identity/source/independence
    checks. Missing unrelated future nodes/coverage are permitted here only;
    its result never declares the review or publication verified.
    """
    roots = _ids(dependency_ids, "dependency closure roots", empty=False)
    if not isinstance(nodes, Mapping):
        _fail("INVALID_NODES", "Dependency preflight needs the trusted completed-node registry")
    selected = {}
    def include(nid):
        if nid in selected:
            return
        if nid not in nodes:
            _fail("MISSING_DEPENDENCY", "The complete child ancestry is unavailable", nid)
        node = nodes[nid]
        opened = _open(node, NODE_TYPE)
        _check_node(opened)
        if opened["node_id"] != nid:
            _fail("NODE_ID_MISMATCH", "Child registry key differs from its actual proof ID")
        selected[nid] = node
        for dep in opened["dependencies"]:
            include(dep)
    for nid in roots:
        include(nid)
    return verify_proof(plan, selected, materials, identities, _dependency_roots=roots)


def prepare_dependency_receipts(plan, nodes, materials, identities, dependency_ids):
    """Authorize receipt projection only after the complete host preflight."""
    roots = _ids(dependency_ids, "dependency receipt roots", empty=False)
    verify_dependency_closure(plan, nodes, materials, identities, roots)
    return {nid: dependency_receipt(nodes[nid]) for nid in roots}


# Explicit names for callers that prefer a gate/builder convention.
validate_proof = verify_proof
make_plan = seal_plan
make_node = seal_node
